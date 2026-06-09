"""Conversational template authoring orchestration.

Pairs the `NoteGenerationProvider.generate_text` chat completion path
with the `Template` Pydantic schema so the assistant's emitted JSON
drafts are validated before they're stored. Failed validation triggers
an internal correction-prompt retry (capped at 2) so an off-shape
emission doesn't leak to the user as a raw 500.

Conversation state lives in `TemplateAuthoringSessionModel`. Each turn:

  1. Append the user's message to history.
  2. Call provider.generate_text with the system prompt + history.
  3. Look for a fenced ```json {"action":"draft_template",...} block.
     If present and the inner template validates → persist it as the
     row's draft_template_json (replacing whatever was there before).
     If present and invalid → re-prompt with the validation errors,
     up to 2 retries, then surface the assistant's last text reply
     without a draft (the conversation continues).
  4. Persist the (now-extended) message history.
  5. Return the assistant message + the (possibly-updated) draft.

No clinical content sneaks in via this path: the system prompt is
structural-only (see system_prompt.py). The provider call is plain
text completion — no tool-calling, no JSON-schema-forcing — so the
LLM has nowhere to encode descriptive-mode violations as "facts."
"""

from __future__ import annotations

import json
import logging
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Optional

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.models import (
    CustomTemplateModel,
    TemplateAuthoringSessionModel,
)
from app.core.types import Template
from app.modules.config.provider_registry import get_registry
from app.modules.providers.base import ChatMessage
from app.modules.template_authoring.system_prompt import SYSTEM_PROMPT

logger = logging.getLogger("aurion.template_authoring")

# Cap message history per authoring session. Beyond this the row would
# bloat unboundedly and the LLM context window gets expensive — we
# truncate from the head, keeping the most recent N turns. The first
# assistant message is sticky (it's the initial "what specialty are
# you building for?" prompt that frames the whole conversation).
_MAX_MESSAGES = 40

# Cap retries when the LLM emits invalid JSON inside the action block.
# The first retry shows the model the validation errors. If it still
# can't recover, we surface the conversation reply without a draft
# rather than 500'ing the request.
_MAX_VALIDATION_RETRIES = 2

# Matches a fenced JSON block:  ```json\n{...}\n```  (greedy on body,
# case-insensitive on the language tag). The (?s) flag is needed so `.`
# matches newlines inside the body.
_FENCED_JSON_RE = re.compile(r"```(?:json)?\s*(\{.*?\})\s*```", re.DOTALL | re.IGNORECASE)

# The initial assistant message used to bootstrap a brand-new authoring
# session. Mirrors the system prompt's "ask one focused question at a
# time" rule so the very first turn is in the right voice.
_BOOTSTRAP_MESSAGE = (
    "Hi! I'll help you design a custom note template for Aurion. "
    "What specialty or visit type is this template for? "
    "(For example: orthopedic post-op follow-up, plastic-surgery wound check, "
    "general musculoskeletal exam.)"
)


@dataclass(frozen=True)
class AuthoringReply:
    """One turn's worth of output to the caller.

    `assistant_message` is the plain-text reply to render in the chat
    bubble. `draft_template` is the latest valid Template draft (if any)
    — when present, the frontend rerenders its preview card. Both can
    coexist on a single turn (the assistant emits a draft AND keeps
    talking).
    """

    assistant_message: str
    draft_template: Optional[Template]


async def start_authoring_session(
    owner_id: uuid.UUID, db: AsyncSession
) -> tuple[TemplateAuthoringSessionModel, AuthoringReply]:
    """Create a fresh authoring session row and return the bootstrap message.

    The first assistant turn is hardcoded (not an LLM call) so the
    initial UX is deterministic and we don't waste a provider call on
    a question we already know the wording of.
    """
    row = TemplateAuthoringSessionModel(
        id=uuid.uuid4(),
        owner_id=owner_id,
        messages_json=json.dumps([
            {"role": "assistant", "content": _BOOTSTRAP_MESSAGE},
        ]),
        draft_template_json=None,
        status="active",
    )
    db.add(row)
    await db.flush()
    return row, AuthoringReply(
        assistant_message=_BOOTSTRAP_MESSAGE, draft_template=None
    )


async def get_authoring_session(
    session_id: uuid.UUID, owner_id: uuid.UUID, db: AsyncSession
) -> Optional[TemplateAuthoringSessionModel]:
    """Fetch an authoring session, scoped to its owner.

    None when the row doesn't exist OR the caller isn't its owner —
    the route handler maps both to 404 so cross-clinician probing
    can't reveal whether a session id exists.
    """
    stmt = select(TemplateAuthoringSessionModel).where(
        TemplateAuthoringSessionModel.id == session_id,
        TemplateAuthoringSessionModel.owner_id == owner_id,
    )
    result = await db.execute(stmt)
    return result.scalar_one_or_none()


async def continue_authoring(
    row: TemplateAuthoringSessionModel,
    user_message: str,
    db: AsyncSession,
) -> AuthoringReply:
    """Append a user turn, call the LLM, parse + validate the reply.

    Caller is responsible for fetching the row (with owner scope) and
    confirming it's `status == 'active'`. This function only handles the
    LLM turn + persistence.
    """
    if row.status != "active":
        raise ValueError(
            f"Cannot continue authoring on a {row.status} session"
        )
    user_message = user_message.strip()
    if not user_message:
        raise ValueError("user_message must be non-empty")

    history = _decode_messages(row.messages_json)
    history.append(ChatMessage(role="user", content=user_message))
    history = _truncate_history(history)

    provider = get_registry().get_note_provider()
    assistant_text, draft = await _generate_with_validation_retry(
        provider, history
    )

    history.append(ChatMessage(role="assistant", content=assistant_text))
    history = _truncate_history(history)

    row.messages_json = _encode_messages(history)
    if draft is not None:
        row.draft_template_json = draft.model_dump_json()
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return AuthoringReply(assistant_message=assistant_text, draft_template=draft)


async def finalize_authoring(
    row: TemplateAuthoringSessionModel, db: AsyncSession
) -> CustomTemplateModel:
    """Promote the draft to a `custom_templates` row owned by the same user.

    Flips this authoring row to `status='completed'` but does NOT delete
    it — the conversation history is part of the audit story for how
    that custom template came to exist.
    """
    if row.status != "active":
        raise ValueError(
            f"Cannot finalize a {row.status} session"
        )
    if row.draft_template_json is None:
        raise ValueError("No draft template to finalize")

    # Re-validate against the live schema before insert — the row could
    # be from an older version of the system, or a developer could have
    # poked at the JSON column directly.
    try:
        draft = Template.model_validate_json(row.draft_template_json)
    except ValidationError as exc:
        raise ValueError(f"Draft no longer valid against Template schema: {exc}") from exc

    # Route the finalized draft through the canonical create path so the
    # per-owner key-uniqueness check AND the custom-template field caps apply
    # here too. Constructing the row directly used to skip both, letting
    # duplicate (owner_id, key) rows form silently — a later lookup then 500s
    # with MultipleResultsFound. Function-level import to avoid module-level
    # coupling (and any import cycle) between the two service modules.
    from app.modules.custom_templates import service as custom_templates_service

    custom = await custom_templates_service.create_for_owner(
        row.owner_id, draft.model_dump(), db
    )

    row.status = "completed"
    row.updated_at = datetime.now(timezone.utc)
    await db.flush()

    return custom


async def upload_template_document(
    owner_id: uuid.UUID, document_text: str, db: AsyncSession
) -> tuple[TemplateAuthoringSessionModel, AuthoringReply]:
    """Seed an authoring session from a pasted template document.

    Same engine as the conversational path: we synthesize a single user
    turn ("here's a template document, extract it"), run the LLM, and
    let the validation-retry loop produce a clean draft. The row is
    persisted in `status='active'` so the physician can keep refining
    the extracted draft via chat if it needs tweaks.
    """
    document_text = document_text.strip()
    if not document_text:
        raise ValueError("Document is empty")

    seed_user_message = (
        "Here is a template document to extract. Output a single valid "
        "draft_template action with the structure that best represents "
        "this document. Use snake_case ids; mark obviously-mandatory "
        "sections as required.\n\n--- DOCUMENT ---\n"
        f"{document_text}"
    )
    history: list[ChatMessage] = [
        ChatMessage(role="assistant", content=_BOOTSTRAP_MESSAGE),
        ChatMessage(role="user", content=seed_user_message),
    ]

    provider = get_registry().get_note_provider()
    assistant_text, draft = await _generate_with_validation_retry(
        provider, history
    )

    history.append(ChatMessage(role="assistant", content=assistant_text))

    row = TemplateAuthoringSessionModel(
        id=uuid.uuid4(),
        owner_id=owner_id,
        messages_json=_encode_messages(history),
        draft_template_json=draft.model_dump_json() if draft else None,
        status="active",
    )
    db.add(row)
    await db.flush()

    return row, AuthoringReply(assistant_message=assistant_text, draft_template=draft)


# ── Internals ──────────────────────────────────────────────────────────────


async def _generate_with_validation_retry(
    provider, history: list[ChatMessage]
) -> tuple[str, Optional[Template]]:
    """Run the LLM turn; if it emits an invalid draft, re-prompt up to
    _MAX_VALIDATION_RETRIES times before giving up and returning the
    raw reply with no draft.

    Returns `(assistant_text, draft_or_none)`. `assistant_text` is what
    the chat UI renders; `draft_or_none` is what the preview card uses.
    """
    working_history = list(history)
    last_assistant = ""

    for attempt in range(_MAX_VALIDATION_RETRIES + 1):
        last_assistant = await provider.generate_text(SYSTEM_PROMPT, working_history)
        extracted = _extract_draft(last_assistant)
        if extracted is None:
            return last_assistant, None
        # extracted is a dict candidate; validate it.
        try:
            template = Template.model_validate(extracted)
            return last_assistant, template
        except ValidationError as exc:
            if attempt == _MAX_VALIDATION_RETRIES:
                logger.warning(
                    "Template authoring: gave up after %d invalid drafts; "
                    "surfacing reply without a draft. last_errors=%s",
                    _MAX_VALIDATION_RETRIES + 1, exc.errors(),
                )
                return last_assistant, None
            # Re-prompt: append the bad assistant reply + a correction
            # request, then loop. We don't persist these intermediate
            # turns — only the final assistant reply makes it to the
            # caller / DB.
            working_history = working_history + [
                ChatMessage(role="assistant", content=last_assistant),
                ChatMessage(
                    role="user",
                    content=(
                        "Your last draft failed schema validation with these "
                        f"errors: {exc.errors()}. Please re-emit a single "
                        "valid draft_template action that satisfies the "
                        "Template schema."
                    ),
                ),
            ]

    return last_assistant, None


def _extract_draft(assistant_text: str) -> Optional[dict]:
    """Pull the inner `template` object out of a fenced action block.

    Returns None when the text has no draft (normal conversational
    turn), or the block isn't an action=draft_template payload, or the
    JSON itself doesn't parse. A subsequent Pydantic validation pass
    catches schema-level invalidity.
    """
    match = _FENCED_JSON_RE.search(assistant_text)
    if not match:
        return None
    try:
        payload = json.loads(match.group(1))
    except json.JSONDecodeError:
        return None
    if not isinstance(payload, dict):
        return None
    if payload.get("action") != "draft_template":
        return None
    template = payload.get("template")
    if not isinstance(template, dict):
        return None
    return template


def _decode_messages(messages_json: str) -> list[ChatMessage]:
    """Parse the persisted JSON into ChatMessage objects.

    Tolerates schema drift — unknown roles default to "user" so a
    stored row that pre-dates a future role addition still loads.
    """
    raw = json.loads(messages_json) if messages_json else []
    out: list[ChatMessage] = []
    for item in raw:
        role = item.get("role", "user")
        if role not in ("user", "assistant"):
            role = "user"
        out.append(ChatMessage(role=role, content=item.get("content", "")))
    return out


def _encode_messages(messages: list[ChatMessage]) -> str:
    return json.dumps(
        [{"role": m.role, "content": m.content} for m in messages]
    )


def _truncate_history(history: list[ChatMessage]) -> list[ChatMessage]:
    """Bound the history at _MAX_MESSAGES, keeping the first assistant
    bootstrap message and the most-recent N-1 turns. Drops middle turns
    when over the cap — preserves "what's the goal" + "what just got
    said" at the cost of mid-conversation context."""
    if len(history) <= _MAX_MESSAGES:
        return history
    # Keep the very first message (almost always the bootstrap) plus
    # the most recent N-1 messages.
    head = history[:1]
    tail = history[-(_MAX_MESSAGES - 1):]
    return head + tail
