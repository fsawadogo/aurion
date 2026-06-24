"""Structural guards for the Prompt Studio tables (PS-01).

No DB: these assert the ORM mapping shape so a careless edit to
``app.core.models`` (a dropped column, a loosened constraint) trips the build.
The migration's apply/rollback is proven separately against Postgres; here we
lock the contract the migration must match.
"""

from __future__ import annotations

from sqlalchemy import UniqueConstraint

from app.core.models import (
    PromptPublicationModel,
    StudioPromptModel,
    StudioPromptVersionModel,
)
from app.core.types import PublicationScope


def _columns(model) -> set[str]:
    return {c.name for c in model.__table__.columns}


def test_studio_prompts_shape() -> None:
    assert StudioPromptModel.__tablename__ == "studio_prompts"
    assert _columns(StudioPromptModel) == {
        "id",
        "job_id",
        "name",
        "created_by",
        "archived_at",
        "created_at",
        "updated_at",
    }


def test_studio_prompt_versions_shape() -> None:
    assert StudioPromptVersionModel.__tablename__ == "studio_prompt_versions"
    assert _columns(StudioPromptVersionModel) == {
        "id",
        "studio_prompt_id",
        "version_no",
        "text",
        "created_by",
        "created_at",
    }


def test_prompt_publications_shape() -> None:
    assert PromptPublicationModel.__tablename__ == "prompt_publications"
    assert _columns(PromptPublicationModel) == {
        "id",
        "job_id",
        "version_id",
        "scope",
        "target_role",
        "target_user_id",
        "published_by",
        "published_at",
        "superseded_at",
    }


def test_version_sequence_is_unique_per_prompt() -> None:
    """Append-only versioning leans on UNIQUE(studio_prompt_id, version_no) —
    without it two saves could collide on a version number. Lock the
    constraint so it cannot be dropped silently."""
    unique_cols = {
        tuple(c.columns.keys())
        for c in StudioPromptVersionModel.__table__.constraints
        if isinstance(c, UniqueConstraint)
    }
    assert ("studio_prompt_id", "version_no") in unique_cols


def test_studio_prompt_versions_cascade_from_parent() -> None:
    """A version's FK to its parent must cascade — deleting a studio prompt
    removes its version history, never orphan rows."""
    parent_fk = next(
        fk
        for fk in StudioPromptVersionModel.__table__.foreign_keys
        if fk.column.table.name == "studio_prompts"
    )
    assert parent_fk.ondelete == "CASCADE"


def test_publication_scope_values() -> None:
    assert [s.value for s in PublicationScope] == ["SELF", "ROLE", "ALL"]
