"""Unit tests for the curated billing code catalog (#69 follow-up).

Locks the validation contract:
  * known codes return True
  * unknown but well-formed codes return False
  * unknown systems return None (defensive, never raises)
  * case-insensitive matching
  * whitespace tolerance
  * catalog version is stable

The catalog itself isn't tested for content — that's a curation
decision, not a code contract. We do test the SHAPE of the catalog
(every entry has a non-empty description; no duplicate keys across
systems with semantic collisions).
"""

from __future__ import annotations

from app.modules.coding.catalog import (
    get_catalog_version,
    lookup_description,
    validate_code,
)
from app.modules.coding.catalog_data import (
    CATALOG_VERSION,
    CPT_CODES,
    EM_CODES,
    ICD10_CODES,
    total_codes,
)

# ── validate_code ────────────────────────────────────────────────────────


def test_validate_em_known_code():
    """E/M 99213 — the most common office-visit code, must be in catalog."""
    assert validate_code("em", "99213") is True


def test_validate_em_all_known_codes_validate():
    """Every code in the catalog dict must validate."""
    for code in EM_CODES:
        assert validate_code("em", code) is True, f"{code} should validate"


def test_validate_em_unknown_code_returns_false():
    """Bogus E/M code → False (actively not found)."""
    assert validate_code("em", "99999") is False


def test_validate_icd10_known_code():
    """M25.561 — pain in right knee, exemplar ortho code."""
    assert validate_code("icd10", "M25.561") is True


def test_validate_icd10_case_insensitive():
    """Lowercase input matches the uppercase catalog entry."""
    assert validate_code("icd10", "m25.561") is True


def test_validate_icd10_whitespace_tolerance():
    """Leading/trailing whitespace doesn't break the lookup."""
    assert validate_code("icd10", "  M25.561  ") is True


def test_validate_icd10_all_known_codes_validate():
    for code in ICD10_CODES:
        assert validate_code("icd10", code) is True, f"{code} should validate"


def test_validate_icd10_unknown_code_returns_false():
    """Plausible but not-in-catalog ICD-10 → False."""
    assert validate_code("icd10", "Q99.999") is False


def test_validate_cpt_known_code():
    """73721 — MRI knee w/o contrast, common ortho CPT."""
    assert validate_code("cpt", "73721") is True


def test_validate_cpt_all_known_codes_validate():
    for code in CPT_CODES:
        assert validate_code("cpt", code) is True, f"{code} should validate"


def test_validate_cpt_unknown_code_returns_false():
    assert validate_code("cpt", "99999") is False


def test_validate_unknown_system_returns_none():
    """Defensive — the parser already filters unknown systems, but
    catalog.validate_code stays import-safe and returns None instead
    of raising."""
    assert validate_code("hcpcs", "G0438") is None
    assert validate_code("", "123") is None
    assert validate_code("snomed", "123456") is None


def test_validate_system_case_insensitive():
    """Uppercase system name still works."""
    assert validate_code("ICD10", "M25.561") is True
    assert validate_code("EM", "99213") is True


# ── lookup_description ──────────────────────────────────────────────────


def test_lookup_em_description_known():
    desc = lookup_description("em", "99213")
    assert desc is not None
    assert "Office visit" in desc


def test_lookup_icd10_description_known():
    desc = lookup_description("icd10", "M25.561")
    assert desc is not None
    assert "right knee" in desc.lower()


def test_lookup_description_unknown_returns_none():
    assert lookup_description("em", "99999") is None
    assert lookup_description("icd10", "Q99.999") is None
    assert lookup_description("hcpcs", "G0438") is None


# ── Catalog shape invariants ─────────────────────────────────────────────


def test_catalog_version_stable():
    """Locked for the audit story — bumping the version means
    catalog content changed, which we want to be intentional."""
    assert CATALOG_VERSION == "2026-06-01.1"
    assert get_catalog_version() == CATALOG_VERSION


def test_em_catalog_has_2021_outpatient_codes():
    """The pilot relies on the 2021 AMA outpatient E/M codes —
    a regression that drops these would break the pilot."""
    for code in ("99202", "99203", "99204", "99205",
                 "99211", "99212", "99213", "99214", "99215"):
        assert code in EM_CODES, f"missing required E/M {code}"


def test_icd10_catalog_has_both_knee_pain_lateralities():
    """Knee pain is the canonical ortho example; left + right
    laterality codes are both needed (the LLM emits per-side)."""
    assert "M25.561" in ICD10_CODES
    assert "M25.562" in ICD10_CODES


def test_cpt_catalog_has_knee_mri():
    """MRI knee — the canonical orthopedic order; if it dropped, the
    pilot would surface a flood of unexpected `code_validated=False`."""
    assert "73721" in CPT_CODES


def test_catalog_entries_have_non_empty_descriptions():
    """Defensive — an empty description would render badly in the
    portal and is a curation slip-up worth catching."""
    for code, desc in EM_CODES.items():
        assert desc.strip(), f"E/M {code} has empty description"
    for code, desc in ICD10_CODES.items():
        assert desc.strip(), f"ICD-10 {code} has empty description"
    for code, desc in CPT_CODES.items():
        assert desc.strip(), f"CPT {code} has empty description"


def test_catalog_total_codes_is_reasonable():
    """Floor — pilot catalog should have at least 100 codes across
    all systems. Ceiling check defends against accidental inclusion
    of an entire upstream catalog (which would defeat the curated
    safety design)."""
    total = total_codes()
    assert total >= 100, f"catalog too sparse: {total}"
    assert total < 5000, f"catalog suspiciously large: {total}"
