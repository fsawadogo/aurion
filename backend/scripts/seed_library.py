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
``key`` among shared templates) keeps its original owner; only content /
display_name / version are refreshed when the starter file differs.

All validation lives in the custom-templates service (schema, field caps,
descriptive-mode gate on any ``system_prompt``) — this script adds no second
validation path, and any invalid starter file aborts the run non-zero so a
bad file can never half-seed the Library.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

# Make the backend package importable when running from backend/ or
# backend/scripts/ — same shim as seed_dev.py.
_backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_root))

STARTER_DIR = _backend_root / "starter_library"

_ALLOWED_OWNER_ROLES = ("ADMIN", "CLINICAL_ADMIN")


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


async def upsert_shared_template(db, owner_id, payload: dict) -> str:
    """Create/refresh ONE shared template. Returns created|updated|unchanged.

    Validation + writes go through the custom-templates service
    (``create_for_owner`` / ``update_owned``) so the starter files obey
    exactly the rules the admin surface enforces — this script adds no
    validation of its own. The shared set is matched by ``key``: an existing
    row keeps its owner (an admin may have authored it by hand first); only
    drifted content is rewritten. Service-level rejections surface as
    ``SeedError`` so one bad file aborts the run non-zero.
    """
    from pydantic import ValidationError

    from app.core.types import Template
    from app.modules.custom_templates import service as svc

    try:
        template = Template.model_validate(payload)
    except ValidationError as exc:
        raise SeedError(f"starter template failed schema validation: {exc}")

    existing = next(
        (row for row in await svc.list_shared(db) if row.key == template.key),
        None,
    )
    try:
        if existing is None:
            await svc.create_for_owner(owner_id, payload, db, is_shared=True)
            return "created"
        if (
            existing.content == template.model_dump_json()
            and existing.display_name == template.display_name
            and existing.version == template.version
        ):
            return "unchanged"
        await svc.update_owned(existing, payload, db)
        return "updated"
    except svc.CustomTemplateError as exc:
        raise SeedError(f"{template.key}: {exc}")


async def resolve_owner(db, owner_email: str):
    """The seeding owner: an existing ADMIN / CLINICAL_ADMIN user id."""
    from sqlalchemy import select

    from app.core.models import UserModel

    result = await db.execute(
        select(UserModel).where(UserModel.email == owner_email)
    )
    user = result.scalar_one_or_none()
    if user is None:
        raise SeedError(f"no user with email {owner_email!r}")
    role = getattr(user.role, "value", user.role)
    if str(role) not in _ALLOWED_OWNER_ROLES:
        raise SeedError(
            f"user {owner_email!r} has role {role} — owner must be one of "
            f"{', '.join(_ALLOWED_OWNER_ROLES)}"
        )
    return user.id


async def seed(owner_email: str) -> dict[str, str]:
    """Upsert every starter template inside one transaction; return
    ``{key: outcome}``."""
    from app.core.database import async_session_factory

    payloads = load_starter_templates()
    outcomes: dict[str, str] = {}
    async with async_session_factory() as db:
        owner_id = await resolve_owner(db, owner_email)
        for payload in payloads:
            outcome = await upsert_shared_template(db, owner_id, payload)
            outcomes[str(payload.get("key"))] = outcome
        await db.commit()
    return outcomes


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--owner-email",
        default=os.environ.get("SEED_LIBRARY_OWNER_EMAIL"),
        help="ADMIN/CLINICAL_ADMIN user who owns newly created rows "
        "(or set SEED_LIBRARY_OWNER_EMAIL)",
    )
    args = parser.parse_args()
    if not args.owner_email:
        print(
            "error: --owner-email (or SEED_LIBRARY_OWNER_EMAIL) is required",
            file=sys.stderr,
        )
        return 2
    try:
        outcomes = asyncio.run(seed(args.owner_email))
    except SeedError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 1
    for key, outcome in outcomes.items():
        print(f"{outcome}: {key}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
