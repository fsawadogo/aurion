"""Unit tests for per-row catalog version persistence (#58 + #69 follow-up).

The contract:
  * coding extraction stores catalog_version on every emitted row
  * orders extraction stores catalog_version on prescription rows
    only; other kinds stay None
  * physician edits re-stamp catalog_version (validation re-runs
    against the CURRENT catalog, not whatever was in effect at
    original extraction)
  * the API response surfaces the field for both shapes

We don't test the migration directly (alembic plumbing is verified
by the existing migrations.py suite); we test the model + service
contracts that depend on the column being there.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

import pytest

from app.core.models import CodingSuggestionModel, NoteOrderModel

# ── Model — column is present ────────────────────────────────────────────


def test_coding_suggestion_model_has_catalog_version_column():
    """Sanity check — the column attribute exists. If a future
    refactor drops the field, this trips before the migration
    becomes inconsistent with the model."""
    row = CodingSuggestionModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        code_system="em",
        code="99213",
        description="x",
        justification="y",
        source_claim_ids=[],
        confidence="medium",
        status="suggested",
        code_validated=True,
        catalog_version="2026-06-01.1",
    )
    assert row.catalog_version == "2026-06-01.1"


def test_note_order_model_has_catalog_version_column():
    row = NoteOrderModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind="prescription",
        details={"drug": "acetaminophen", "dose": "500mg",
                 "frequency": "q6h", "indication": "pain"},
        source_claim_ids=[],
        status="draft",
        drug_validated=True,
        catalog_version="2026-06-01.1",
    )
    assert row.catalog_version == "2026-06-01.1"


def test_catalog_version_defaults_to_none():
    """Column is nullable; legacy / unset rows have None."""
    row = NoteOrderModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind="lab",
        details={"panel": "CBC", "indication": "workup"},
        source_claim_ids=[],
        status="draft",
    )
    assert row.catalog_version is None


# ── Helper for service tests (re-used from sibling test files) ───────────


class _MockSession:
    def __init__(self) -> None:
        self.added: list = []

    def add(self, row) -> None:
        self.added.append(row)

    async def flush(self) -> None:
        return None


# ── Catalog version comes from the catalog modules ───────────────────────


def test_coding_catalog_get_version_returns_string():
    """The version string is what gets persisted on each row."""
    from app.modules.coding.catalog import get_catalog_version

    v = get_catalog_version()
    assert isinstance(v, str)
    assert v  # non-empty
    # Fits the 32-char column cap
    assert len(v) <= 32


def test_orders_catalog_get_version_returns_string():
    from app.modules.orders.drug_catalog import get_catalog_version

    v = get_catalog_version()
    assert isinstance(v, str)
    assert v
    assert len(v) <= 32


# ── Service integration — edit re-stamps catalog_version ────────────────


@pytest.mark.asyncio
async def test_orders_edit_restamps_catalog_version():
    """A physician edit of a prescription order re-runs validation +
    re-stamps catalog_version. The override is against the current
    catalog state, not whatever was in effect at extraction."""
    from app.modules.orders import service as orders_service
    from app.modules.orders.drug_catalog import get_catalog_version

    db = _MockSession()
    row = NoteOrderModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind="prescription",
        details={
            "drug": "acetaminophen", "dose": "500mg",
            "frequency": "q6h", "indication": "pain",
        },
        source_claim_ids=[],
        status="draft",
        drug_validated=True,
        # Simulate row extracted under an older catalog version
        catalog_version="2020-01-01.1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )

    updated = await orders_service.edit_details(
        row,
        {
            "drug": "ibuprofen", "dose": "400mg",
            "frequency": "q6h", "indication": "pain",
        },
        db,  # type: ignore[arg-type]
    )
    # Catalog version should now match the current catalog
    assert updated.catalog_version == get_catalog_version()
    # Drug validation should have re-run (ibuprofen is in catalog)
    assert updated.drug_validated is True


@pytest.mark.asyncio
async def test_orders_edit_leaves_catalog_version_for_non_prescription():
    """Editing a lab order doesn't touch catalog_version (lab rows
    don't get drug-validated)."""
    from app.modules.orders import service as orders_service

    db = _MockSession()
    row = NoteOrderModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        kind="lab",
        details={"panel": "CBC", "indication": "workup"},
        source_claim_ids=[],
        status="draft",
        catalog_version=None,
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    updated = await orders_service.edit_details(
        row,
        {"panel": "CMP", "indication": "workup"},
        db,  # type: ignore[arg-type]
    )
    # Still None — lab kind doesn't get a catalog stamp.
    assert updated.catalog_version is None
    assert updated.drug_validated is None


@pytest.mark.asyncio
async def test_coding_edit_restamps_catalog_version():
    """Same contract for coding rows: edit re-runs validation +
    re-stamps the catalog version."""
    from app.modules.coding import service as coding_service
    from app.modules.coding.catalog import get_catalog_version

    db = _MockSession()
    row = CodingSuggestionModel(
        id=uuid.uuid4(),
        session_id=uuid.uuid4(),
        code_system="icd10",
        code="M25.561",
        description="Pain in right knee",
        justification="anchored to c1",
        source_claim_ids=[],
        confidence="high",
        status="suggested",
        code_validated=True,
        catalog_version="2020-01-01.1",
        created_at=datetime.now(timezone.utc),
        updated_at=datetime.now(timezone.utc),
    )
    updated, previous_code = await coding_service.edit(
        row, "M25.562", "Pain in left knee",
        db,  # type: ignore[arg-type]
    )
    assert previous_code == "M25.561"
    assert updated.code == "M25.562"
    assert updated.code_validated is True
    assert updated.catalog_version == get_catalog_version()
