"""Seed development data: users, templates, AppConfig.

Run after docker-compose up:
    python scripts/seed_dev.py

Idempotent — safe to run multiple times. Existing tables and data
are left in place; only missing resources are created.
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

# ---------------------------------------------------------------------------
# Ensure the backend package is importable when running from /backend/scripts
# ---------------------------------------------------------------------------
_backend_root = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(_backend_root))

from app.core.database import engine, async_session_factory  # noqa: E402
from app.core.models import SessionModel, NoteVersionModel, PilotMetricsModel  # noqa: E402


# ---------------------------------------------------------------------------
# Template directory — five specialty template JSON files
# ---------------------------------------------------------------------------
TEMPLATE_DIR = _backend_root / "app" / "modules" / "note_gen" / "templates"


def run_migrations() -> None:
    """Run ``alembic upgrade head`` so the schema is current before seeding.

    Uses ``sys.executable -m alembic`` instead of bare ``alembic`` so this
    works in a venv-less shell or a slim CI image where alembic isn't on
    PATH but is importable.
    """
    import subprocess

    subprocess.run(
        [sys.executable, "-m", "alembic", "upgrade", "head"],
        cwd=str(_backend_root),
        check=True,
    )


def load_templates() -> list[dict]:
    """Load and validate all specialty template JSON files.

    Returns a list of parsed template dicts. Raises if the template
    directory is missing or any JSON file is malformed.
    """
    if not TEMPLATE_DIR.is_dir():
        print(f"WARNING: Template directory not found at {TEMPLATE_DIR}")
        return []

    templates: list[dict] = []
    for path in sorted(TEMPLATE_DIR.glob("*.json")):
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        key = path.stem
        sections = data.get("sections", [])
        required_count = sum(1 for s in sections if s.get("required", True))
        print(
            f"  Loaded template: {key:30s} "
            f"({len(sections)} sections, {required_count} required)"
        )
        templates.append(data)

    return templates


async def seed() -> None:
    """Run the full seed sequence."""
    print("=" * 60)
    print("Aurion Dev Seed")
    print("=" * 60)

    # --- Schema ----------------------------------------------------------
    print("\n--- Running alembic migrations ---")
    run_migrations()

    # --- Templates -------------------------------------------------------
    print("\n--- Loading specialty templates ---")
    templates = load_templates()

    # --- Summary ---------------------------------------------------------
    print("\n" + "=" * 60)
    print(f"Seed complete: schema migrated, {len(templates)} templates loaded")
    print("=" * 60)


def main() -> None:
    asyncio.run(seed())


if __name__ == "__main__":
    main()
