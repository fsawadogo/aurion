"""Seed the shared template Library from ``backend/starter_library/`` (loop-2).

Every ``*.json`` in ``starter_library/`` is upserted as a SHARED custom
template (``is_shared=True``, tpl-04) so it appears read-only in every
clinician's Templates → Library and resolves at note generation via
``get_owned_or_shared`` — the mobile-safe path: no client key lists, iOS
picks it up through the existing resolution chain with zero app changes.

Run (idempotent — rerunning creates nothing and updates nothing unless a
starter file changed):

    python scripts/seed_library.py --owner-email admin@example.com

The owner email must resolve to an existing ADMIN / CLINICAL_ADMIN user —
seeded rows follow the same ownership model as templates authored in the
admin Shared Templates surface. A row that already exists (matched by
``key`` among shared templates) keeps its original owner; only drifted
content is refreshed.

The custom-templates service stays the single validation gate (schema,
field caps, descriptive-mode gate on any ``system_prompt``); the script
parses a template itself only to canonicalize for the drift compare. Any
invalid starter file aborts the run non-zero, and nothing commits unless
every file seeded — a bad file can never half-seed the Library.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path
from typing import TYPE_CHECKING

# Make the backend package importable when running from backend/ or
# backend/scripts/ — same shim as seed_dev.py. App imports stay
# function-local below it (ruff E402 would reject them at top level);
# type-only imports are exempt and carry the annotations.
_backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_root))

if TYPE_CHECKING:
    import uuid

    from sqlalchemy.ext.asyncio import AsyncSession

STARTER_DIR = _backend_root / "starter_library"


class SeedError(Exception):
    """Fatal seeding problem — printed and exits non-zero."""


def load_starter_templates(directory: Path = STARTER_DIR) -> list[dict]:
    """Parse every ``*.json`` starter file, sorted for a stable run order.

    Raises ``SeedError`` on unreadable/invalid JSON — a broken starter file
    must fail the whole run loudly rather than seed a partial Library.
    """
    if not directory.is_dir():
        raise SeedError(f"starter_library directory not found: {directory}")
    payloads: list[dict] = []
    for path in sorted(directory.glob("*.json")):
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as exc:
            raise SeedError(f"{path.name}: unreadable or invalid JSON ({exc})")
        if not isinstance(payload, dict):
            raise SeedError(f"{path.name}: top-level JSON must be an object")
        payloads.append(payload)
    if not payloads:
        raise SeedError(f"no *.json starter files in {directory}")
    return payloads


async def upsert_shared_template(
    db: AsyncSession,
    owner_id: uuid.UUID,
    payload: dict,
    shared_by_key: dict[str, list],
) -> str:
    """Create/refresh ONE shared template. Returns created|updated|unchanged.

    ``shared_by_key`` is the run's snapshot of the shared set ({key: rows}).
    More than one shared row per key aborts: the DB only enforces
    (owner_id, key) uniqueness, so cross-owner duplicates are possible, and
    updating "whichever sorted first" could silently rewrite a hand-authored
    admin row. Writes delegate to the custom-templates service
    (``create_for_owner`` / ``update_owned``) — the single validation gate;
    two starter files sharing a key hit the service's duplicate check on the
    second create and abort, as a starter configuration error should.
    """
    from pydantic import ValidationError

    from app.core.types import Template
    from app.modules.custom_templates import service as svc

    key = payload.get("key")
    matches = shared_by_key.get(key, [])
    if len(matches) > 1:
        raise SeedError(
            f"{key}: {len(matches)} shared templates share this key "
            "(different owners) — resolve the duplicate before seeding"
        )
    try:
        if not matches:
            await svc.create_for_owner(owner_id, payload, db, is_shared=True)
            return "created"
        existing = matches[0]
        try:
            template = Template.model_validate(payload)
        except ValidationError as exc:
            raise SeedError(f"{key}: failed schema validation: {exc}")
        # Canonical-to-canonical compare: stored content was written via the
        # same model_dump_json, and display_name/version live inside it, so
        # content equality alone means "no drift".
        if existing.content == template.model_dump_json():
            return "unchanged"
        await svc.update_owned(existing, payload, db)
        return "updated"
    except svc.CustomTemplateError as exc:
        raise SeedError(f"{key}: {exc}")


async def resolve_owner(db: AsyncSession, owner_email: str) -> uuid.UUID:
    """The seeding owner: an existing ADMIN / CLINICAL_ADMIN user id.

    The email is matched exactly (case-sensitive) — registration lowercases
    stored emails, so pass the address in lowercase."""
    from app.core.types import UserRole
    from app.modules.auth import users_repository as users_repo

    user = await users_repo.get_by_email(db, owner_email)
    if user is None:
        raise SeedError(f"no user with email {owner_email!r}")
    allowed = (UserRole.ADMIN, UserRole.CLINICAL_ADMIN)
    if user.role not in allowed:
        raise SeedError(
            f"user {owner_email!r} has role {user.role} — owner must be one "
            f"of {', '.join(r.value for r in allowed)}"
        )
    return user.id


async def seed(owner_email: str) -> tuple[dict[str, str], list[str]]:
    """Upsert every starter template inside ONE transaction.

    Returns ``({key: outcome}, unmanaged_shared_keys)``. The single commit
    sits after the loop on purpose: any failure rolls the whole run back, so
    a bad starter file can never half-seed the Library. Renaming a starter
    file's ``key`` creates a NEW row and orphans the old one (it will show
    up as unmanaged) — delete the orphan via the admin Shared Templates
    surface.
    """
    from app.core.database import async_session_factory
    from app.modules.custom_templates import service as svc

    payloads = load_starter_templates()
    outcomes: dict[str, str] = {}
    async with async_session_factory() as db:
        owner_id = await resolve_owner(db, owner_email)
        shared_by_key: dict[str, list] = {}
        for row in await svc.list_shared(db):
            shared_by_key.setdefault(row.key, []).append(row)
        for payload in payloads:
            key = payload.get("key")
            # Two starter FILES declaring one key would silently last-write-
            # win on an existing DB (both hit the update path) — the DB's
            # per-owner uniqueness can't catch it, so the script must.
            if key in outcomes:
                raise SeedError(
                    f"{key}: two starter files declare this key — "
                    "resolve the duplicate before seeding"
                )
            outcome = await upsert_shared_template(
                db, owner_id, payload, shared_by_key
            )
            outcomes[payload["key"]] = outcome
        await db.commit()
    # The Library is only as reproducible as starter_library/. Name the
    # shared rows this run does NOT manage so an operator can't mistake a
    # partly seeded Library for a fully code-managed one on a DB rebuild.
    unmanaged = sorted(set(shared_by_key) - set(outcomes))
    return outcomes, unmanaged


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner-email",
        default=os.environ.get("SEED_LIBRARY_OWNER_EMAIL"),
        help="ADMIN/CLINICAL_ADMIN user who owns newly created rows, matched "
        "exactly (case-sensitive; stored emails are lowercase). Or set "
        "SEED_LIBRARY_OWNER_EMAIL.",
    )
    args = parser.parse_args()
    owner_email = (args.owner_email or "").strip()
    if not owner_email:
        print(
            "error: --owner-email (or SEED_LIBRARY_OWNER_EMAIL) is required",
            file=sys.stderr,
        )
        return 2
    try:
        outcomes, unmanaged = asyncio.run(seed(owner_email))
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for key, outcome in outcomes.items():
        print(f"{outcome}: {key}")
    if unmanaged:
        print("unmanaged (not in starter_library/): " + ", ".join(unmanaged))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
