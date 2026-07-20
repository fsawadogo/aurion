"""TE-2 — the session's template is available in Stage 2.

Stage 2 has never held the `Template`, only the `Note` (which carries a bare
`specialty` string). That is why the frames path is template-blind: captioning
doesn't know which section it feeds, so it writes generic descriptions that get
pasted in verbatim (`vision/service.py:882`) — Marie's "descriptions physiques"
clutter.

`resolve_session_template` closes that. The load-bearing property is that Stage
2 gets **the same template Stage 1 used** — resolved from the session's stored
PIN, never re-derived from `specialty`, which would silently diverge for any
session pinned to a context or custom template.

This slice is deliberately inert: TE-3 aims captioning with the template,
TE-4 formats + routes the merged claim with it.
"""

from __future__ import annotations

import uuid
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from app.core.types import Template, TemplateSection
from app.modules.note_gen.service import (
    get_template,
    resolve_session_template,
)


def _session(
    *,
    specialty: str = "orthopedic_surgery",
    template_key: str | None = None,
    custom_template_id: uuid.UUID | None = None,
) -> SimpleNamespace:
    """A session row stand-in carrying the same pin fields the ORM row has."""
    return SimpleNamespace(
        id=uuid.uuid4(),
        specialty=specialty,
        template_key=template_key,
        custom_template_id=custom_template_id,
    )


def _custom_template_row(key: str = "marie-knee") -> SimpleNamespace:
    """A custom_templates row whose `content` parses as a Template."""
    tpl = Template(
        key=key,
        display_name="Marie — knee consult",
        sections=[
            TemplateSection(id="chief_complaint", title="Chief complaint"),
            TemplateSection(id="physical_exam", title="Physical examination"),
        ],
    )
    return SimpleNamespace(content=tpl.model_dump_json())


# ── AC-1..AC-4 · the resolver returns what Stage 1 used ─────────────────────


@pytest.mark.asyncio
async def test_resolves_same_builtin_template_as_stage1():
    """AC-1 — a session pinned to a built-in key resolves to that template,
    NOT to its specialty default. Those differ here on purpose: pinned
    `general` vs specialty `orthopedic_surgery`."""
    session = _session(specialty="orthopedic_surgery", template_key="general")

    resolved = await resolve_session_template(session, AsyncMock())

    assert resolved.key == "general"
    assert resolved.key == get_template("general").key
    # The bug this guards: re-deriving from specialty would give ortho.
    assert resolved.key != "orthopedic_surgery"


@pytest.mark.asyncio
async def test_resolves_pinned_custom_template():
    """AC-2 — a session pinned to a custom template resolves to that row's
    content, not to any built-in."""
    cid = uuid.uuid4()
    session = _session(custom_template_id=cid)

    with patch(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(return_value=_custom_template_row()),
    ):
        resolved = await resolve_session_template(session, AsyncMock())

    assert resolved.key == "marie-knee"
    assert resolved.display_name == "Marie — knee consult"


@pytest.mark.asyncio
async def test_unpinned_session_falls_back_to_specialty():
    """AC-3 — no pin → the specialty default, byte-for-byte the path Stage 1
    already takes for an unpinned session."""
    session = _session(specialty="plastic_surgery")

    resolved = await resolve_session_template(session, AsyncMock())

    assert resolved.key == get_template("plastic_surgery").key


@pytest.mark.asyncio
async def test_stale_custom_pin_degrades_without_raising():
    """AC-4 — a deleted custom pin must degrade to the specialty default, not
    raise. Stage 2 enrichment can never be broken by a stale binding."""
    session = _session(specialty="plastic_surgery", custom_template_id=uuid.uuid4())

    with patch(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(return_value=None),  # row deleted after the snapshot
    ):
        resolved = await resolve_session_template(session, AsyncMock())

    assert resolved.key == "plastic_surgery"


@pytest.mark.asyncio
async def test_lookup_failure_degrades_without_raising():
    """AC-4 (sibling) — a DB error during the custom lookup degrades too."""
    session = _session(specialty="general", custom_template_id=uuid.uuid4())

    with patch(
        "app.modules.custom_templates.service.get_by_id",
        AsyncMock(side_effect=RuntimeError("db down")),
    ):
        resolved = await resolve_session_template(session, AsyncMock())

    assert resolved.key == "general"


# ── The Stage-2 caller's contract ───────────────────────────────────────────


@pytest.mark.asyncio
async def test_accepts_the_session_row_shape_stage2_actually_has():
    """Stage 2 will call this with the ORM `SessionModel` row it already loads
    for the evidence mode (`api/v1/vision.py`), so the resolver must work off
    exactly that shape — `specialty` + the two pin columns — and nothing else.

    Pinned here because TE-3 is what wires the call; if the resolver ever grew
    a dependency on a field Stage 2 doesn't have, TE-3 would fail at runtime
    rather than at review.
    """
    session = _session(specialty="musculoskeletal", template_key="musculoskeletal")

    resolved = await resolve_session_template(session, AsyncMock())

    assert resolved.key == "musculoskeletal"
    # No attribute beyond specialty + the two pin fields was required.
    assert set(vars(session)) == {
        "id",
        "specialty",
        "template_key",
        "custom_template_id",
    }
