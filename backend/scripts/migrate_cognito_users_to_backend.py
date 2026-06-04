#!/usr/bin/env python3
"""One-shot migration: Cognito user pool → backend ``users`` table.

AUTH-PIVOT-BACKEND. Read every user from the configured Cognito user
pool, insert them into the backend ``users`` table with a freshly-
generated temporary password, print ``email\\ttemp_password`` per
migrated user. Operator distributes the temp passwords out-of-band.

Behavior
--------
* **Idempotent.** A user whose email already exists in the backend
  table is skipped — re-running is safe.
* **MFA NOT migrated.** Cognito stores its TOTP secrets in its own
  vault; we can't re-derive them. Users re-enroll via
  ``GET /api/v1/auth/mfa/setup`` after their first backend login.
* **Run from a workstation with Cognito read perms** (or from an
  ECS task with the migration IAM role). The script never writes to
  Cognito.

Usage
-----
::

    cd backend
    # Dry run — list what would be migrated, no DB writes.
    python3 scripts/migrate_cognito_users_to_backend.py --dry-run

    # Real run — inserts users + prints `email\\ttemp_password` to stdout.
    python3 scripts/migrate_cognito_users_to_backend.py \\
        --cognito-user-pool-id ca-central-1_xxxxxxxxx

The output stream is deliberately TSV so the operator can pipe to
``column -t`` for a clean table, or to a 1Password ``op`` import.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from typing import Any

import boto3

# Set up Python path so ``app.*`` imports resolve when run from the
# backend dir. Mirrors seed_dev.py's bootstrap shape.
_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, _BACKEND_DIR)

from app.api.v1.auth import generate_temp_password  # noqa: E402
from app.core.database import async_session_factory  # noqa: E402
from app.core.models import UserModel  # noqa: E402
from app.core.types import UserRole  # noqa: E402
from app.modules.auth import users_repository as users_repo  # noqa: E402
from app.modules.auth.passwords import hash_password  # noqa: E402

logger = logging.getLogger("aurion.migrate_cognito")


# ── CLI ────────────────────────────────────────────────────────────────────


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--cognito-user-pool-id",
        default=os.getenv("COGNITO_USER_POOL_ID", ""),
        help="Cognito user pool id (defaults to $COGNITO_USER_POOL_ID).",
    )
    parser.add_argument(
        "--region",
        default=os.getenv("AWS_DEFAULT_REGION", "ca-central-1"),
        help="AWS region for the Cognito + DB clients.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="List users that would be migrated; no DB writes.",
    )
    return parser.parse_args()


# ── Cognito read ───────────────────────────────────────────────────────────


def list_cognito_users(
    *, pool_id: str, region: str
) -> list[dict[str, Any]]:
    """Paginate list_users across the entire Cognito pool.

    Returns a list of ``{"email": str, "role": UserRole, "full_name": str}``
    dicts. Users with no email attribute are skipped (a Cognito row
    with no email is unusable for backend login anyway).
    """
    client = boto3.client("cognito-idp", region_name=region)
    users: list[dict[str, Any]] = []
    pagination_token: str | None = None

    while True:
        kwargs: dict[str, Any] = {"UserPoolId": pool_id, "Limit": 60}
        if pagination_token:
            kwargs["PaginationToken"] = pagination_token
        response = client.list_users(**kwargs)
        for raw in response.get("Users", []):
            mapped = _map_cognito_user(client, pool_id, raw)
            if mapped is not None:
                users.append(mapped)
        pagination_token = response.get("PaginationToken")
        if not pagination_token:
            break

    return users


def _map_cognito_user(
    client: Any, pool_id: str, raw: dict[str, Any]
) -> dict[str, Any] | None:
    """Pull the email + full_name attributes and the role from group
    membership. Returns None if email is absent."""
    attrs = {a["Name"]: a["Value"] for a in raw.get("Attributes", [])}
    email = attrs.get("email", "").strip().lower()
    if not email:
        return None

    full_name = attrs.get("name") or attrs.get("preferred_username") or ""

    # Group membership → role. We use the same priority map the Cognito
    # JWKS path applied historically — ADMIN > COMPLIANCE_OFFICER >
    # EVAL_TEAM > CLINICIAN.
    try:
        groups_response = client.admin_list_groups_for_user(
            Username=raw["Username"], UserPoolId=pool_id
        )
        group_names = [
            g.get("GroupName", "").upper()
            for g in groups_response.get("Groups", [])
        ]
    except Exception as e:
        logger.warning(
            "list-groups failed for %s: %s — defaulting to CLINICIAN",
            email,
            type(e).__name__,
        )
        group_names = []

    role = _resolve_role(group_names)
    return {"email": email, "full_name": full_name, "role": role}


def _resolve_role(groups: list[str]) -> UserRole:
    normalized = set(groups)
    if "ADMIN" in normalized or "ADMINS" in normalized:
        return UserRole.ADMIN
    if (
        "COMPLIANCE_OFFICER" in normalized
        or "COMPLIANCE_OFFICERS" in normalized
    ):
        return UserRole.COMPLIANCE_OFFICER
    if "EVAL_TEAM" in normalized or "EVAL" in normalized:
        return UserRole.EVAL_TEAM
    return UserRole.CLINICIAN


# ── DB write ───────────────────────────────────────────────────────────────


async def migrate(
    cognito_users: list[dict[str, Any]], *, dry_run: bool
) -> tuple[int, int]:
    """Insert every Cognito user that isn't already in the backend table.

    Returns ``(migrated_count, skipped_count)``. Prints
    ``email\\ttemp_password`` for each migrated user; nothing for skips.
    """
    migrated = 0
    skipped = 0

    async with async_session_factory() as db:
        for u in cognito_users:
            existing = await users_repo.get_by_email(db, u["email"])
            if existing is not None:
                skipped += 1
                continue

            temp_password = generate_temp_password()
            if dry_run:
                print(f"{u['email']}\tWOULD-MIGRATE\t{u['role'].value}")
                migrated += 1
                continue

            db.add(
                UserModel(
                    email=u["email"],
                    full_name=u["full_name"] or u["email"].split("@")[0],
                    role=u["role"],
                    password_hash=hash_password(temp_password),
                )
            )
            # Flush per user so the next iteration's get_by_email sees
            # the new row if the same email somehow appears twice.
            await db.flush()
            print(f"{u['email']}\t{temp_password}\t{u['role'].value}")
            migrated += 1

        if not dry_run:
            await db.commit()

    return migrated, skipped


# ── Entry point ────────────────────────────────────────────────────────────


async def _main() -> int:
    logging.basicConfig(
        level=logging.INFO, format="%(levelname)s: %(message)s"
    )
    args = parse_args()
    if not args.cognito_user_pool_id:
        logger.error(
            "--cognito-user-pool-id (or COGNITO_USER_POOL_ID env var) is required"
        )
        return 2

    logger.info(
        "Reading users from Cognito pool %s (region=%s)%s",
        args.cognito_user_pool_id,
        args.region,
        " [dry run]" if args.dry_run else "",
    )
    cognito_users = list_cognito_users(
        pool_id=args.cognito_user_pool_id, region=args.region
    )
    logger.info("Found %d Cognito users.", len(cognito_users))

    print("# email\ttemp_password\trole", flush=True)
    migrated, skipped = await migrate(cognito_users, dry_run=args.dry_run)
    logger.info(
        "Migrated %d, skipped %d (already in backend table).",
        migrated,
        skipped,
    )
    return 0


def main() -> None:
    sys.exit(asyncio.run(_main()))


if __name__ == "__main__":
    main()
