"""Migration smoke tests.

These run without a database. They verify that the alembic script
collection is structurally sound:

  * Exactly one head, no branched history.
  * Every revision exposes both ``upgrade`` and ``downgrade`` callables.
  * Offline SQL rendering succeeds for both directions — this catches
    malformed ``op.create_table`` calls, missing imports, and dialect
    mismatches without needing a live Postgres.
  * The baseline's enum values stay in sync with ``app.core.types``.

A full upgrade/downgrade round-trip against a real Postgres lives in CI
(via testcontainers); these tests run on every developer push.
"""

from __future__ import annotations

import io
from pathlib import Path

import pytest
from alembic.config import Config
from alembic.script import ScriptDirectory

from alembic import command

BACKEND_ROOT = Path(__file__).resolve().parent.parent.parent


def _alembic_config(output_buffer: io.StringIO | None = None) -> Config:
    cfg = Config(str(BACKEND_ROOT / "alembic.ini"))
    if output_buffer is not None:
        cfg.attributes["connection"] = None
        cfg.set_main_option("sqlalchemy.url", "postgresql+psycopg2://x:x@localhost/x")
        cfg.output_buffer = output_buffer
    return cfg


def test_single_head() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    heads = script.get_heads()
    assert len(heads) == 1, f"expected a single migration head, got: {heads}"


def test_every_revision_has_upgrade_and_downgrade() -> None:
    script = ScriptDirectory.from_config(_alembic_config())
    for rev in script.walk_revisions():
        mod = rev.module
        assert callable(getattr(mod, "upgrade", None)), f"{rev.revision} missing upgrade()"
        assert callable(getattr(mod, "downgrade", None)), f"{rev.revision} missing downgrade()"


@pytest.mark.parametrize(
    "direction",
    [("upgrade", "head"), ("downgrade", "head:base")],
    ids=["upgrade", "downgrade"],
)
def test_offline_sql_renders(direction: tuple[str, str]) -> None:
    buf = io.StringIO()
    cfg = _alembic_config(output_buffer=buf)
    op, rev = direction
    getattr(command, op)(cfg, rev, sql=True)
    sql = buf.getvalue()
    assert "BEGIN" in sql
    assert "COMMIT" in sql


def test_baseline_creates_expected_tables() -> None:
    buf = io.StringIO()
    cfg = _alembic_config(output_buffer=buf)
    command.upgrade(cfg, "head", sql=True)
    sql = buf.getvalue()
    expected = {
        "users",
        "sessions",
        "physician_profiles",
        "transcripts",
        "note_versions",
        "custom_templates",
        "pilot_metrics",
        "stage2_jobs",
    }
    for table in expected:
        assert f"CREATE TABLE {table}" in sql, f"baseline missing table: {table}"
    assert "CREATE TYPE user_role AS ENUM" in sql
    assert "CREATE TYPE session_state AS ENUM" in sql


def test_baseline_enums_match_python_enums() -> None:
    """Guard against the baseline drifting from app.core.types.

    Both ``UserRole`` and ``SessionState`` are still in flux pre-pilot.
    If a value is added to the Python enum, this test fires so the dev
    writes an ``alter_type`` migration rather than silently desyncing.
    """
    import importlib.util

    from app.core.types import SessionState, UserRole

    baseline_path = next((BACKEND_ROOT / "alembic" / "versions").glob("*_0001_*.py"))
    spec = importlib.util.spec_from_file_location("_baseline", baseline_path)
    assert spec is not None and spec.loader is not None
    baseline = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(baseline)

    assert set(baseline.USER_ROLE_VALUES) == {m.value for m in UserRole}, (
        "UserRole enum drifted from baseline migration — write an alter_type migration"
    )
    assert set(baseline.SESSION_STATE_VALUES) == {m.value for m in SessionState}, (
        "SessionState enum drifted from baseline migration — write an alter_type migration"
    )
