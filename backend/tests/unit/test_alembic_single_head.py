"""Unit guard: the alembic history stays linear with a single head.

A duplicate/branched head is a *deploy-breaking* condition — the container
entrypoint runs ``alembic upgrade head`` on boot, which aborts with
"Multiple head revisions are present" and the task crash-loops, so the new
image never serves and the old one keeps running.

An equivalent check already lives in ``tests/integration/test_migrations.py``,
but PR CI runs **only** ``tests/unit/`` (see ci.yml), so that guard never
gates a merge. This unit copy runs on every PR. It needs no database —
``ScriptDirectory`` reads the migration files only.

Regression: two migrations were merged both claiming ``revision = "0047"``
off ``down_revision = "0046"`` (org_visit_type_templates + schedule_entries),
branching the head and taking dev down on the next deploy.
"""

from __future__ import annotations

from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _script() -> ScriptDirectory:
    return ScriptDirectory.from_config(Config(str(BACKEND_ROOT / "alembic.ini")))


def test_single_migration_head() -> None:
    heads = _script().get_heads()
    assert len(heads) == 1, (
        f"expected exactly one alembic head, got {len(heads)}: {heads}. "
        "A branched head breaks `alembic upgrade head` on container boot."
    )


def test_revision_ids_are_unique() -> None:
    """Two files sharing a `revision` id is what produces the branch — assert
    every revision id appears exactly once so the collision is caught at the
    source, with a message that names the duplicate."""
    seen: dict[str, int] = {}
    for rev in _script().walk_revisions():
        seen[rev.revision] = seen.get(rev.revision, 0) + 1
    dupes = {r: n for r, n in seen.items() if n > 1}
    assert not dupes, f"duplicate alembic revision id(s): {dupes}"
