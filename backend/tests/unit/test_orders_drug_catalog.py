"""Unit tests for the curated drug catalog (#58 follow-up).

Locks the contract:
  * known generic drugs return True
  * known brand drugs return True (via brand → generic resolution)
  * unknown drugs return False
  * case-insensitive + whitespace-tolerant
  * combination separator canonicalization (`/`, ` + `, ` with `)
  * empty/whitespace-only names return False
  * catalog SHAPE invariants (required pilot drugs present;
    BRAND_TO_GENERIC values all resolve to GENERIC_DRUGS)
"""

from __future__ import annotations

from app.modules.orders.drug_catalog import (
    get_catalog_version,
    lookup_drug_class,
    resolve_to_generic,
    validate_drug,
)
from app.modules.orders.drug_catalog_data import (
    BRAND_TO_GENERIC,
    CATALOG_VERSION,
    GENERIC_DRUGS,
    normalize_drug_name,
    total_drugs,
)

# ── validate_drug ────────────────────────────────────────────────────────


def test_validate_known_generic_drug():
    """Acetaminophen — the most common post-op analgesic."""
    assert validate_drug("acetaminophen") is True


def test_validate_known_brand_drug():
    """Brand → generic resolution path."""
    assert validate_drug("Tylenol") is True


def test_validate_case_insensitive():
    """All three case variants resolve."""
    assert validate_drug("IBUPROFEN") is True
    assert validate_drug("Ibuprofen") is True
    assert validate_drug("ibuprofen") is True


def test_validate_whitespace_tolerance():
    """Leading/trailing whitespace doesn't break lookup."""
    assert validate_drug("  amoxicillin  ") is True
    assert validate_drug("  TYLENOL  ") is True


def test_validate_unknown_returns_false():
    """Hallucinated drug name → False (caution-worthy)."""
    assert validate_drug("furbleamabin") is False


def test_validate_empty_returns_false():
    """Empty / whitespace-only input is invalid."""
    assert validate_drug("") is False
    assert validate_drug("   ") is False


def test_validate_combination_drug_canonical_form():
    """Combo product in canonical form (slash separator)."""
    assert validate_drug("acetaminophen/codeine") is True
    assert validate_drug("amoxicillin/clavulanate") is True


def test_validate_combination_drug_with_plus_separator():
    """`acetaminophen + codeine` normalizes to the slashed form."""
    assert validate_drug("acetaminophen + codeine") is True


def test_validate_combination_drug_with_with_separator():
    """`acetaminophen with codeine` also normalizes."""
    assert validate_drug("acetaminophen with codeine") is True


def test_validate_brand_combo_resolves_to_generic_combo():
    """Percocet → acetaminophen/oxycodone → True."""
    assert validate_drug("Percocet") is True


def test_validate_tylenol_3_brand_variants():
    """Both `Tylenol 3` and `Tylenol #3` are common in practice
    (hash + space + number); both should resolve."""
    assert validate_drug("Tylenol 3") is True
    assert validate_drug("tylenol #3") is True


def test_validate_all_generic_drugs():
    """Every entry in GENERIC_DRUGS must validate as itself."""
    for drug in GENERIC_DRUGS:
        assert validate_drug(drug) is True, f"{drug} should validate"


def test_validate_all_brand_drugs():
    """Every entry in BRAND_TO_GENERIC must resolve through to True."""
    for brand in BRAND_TO_GENERIC:
        assert validate_drug(brand) is True, f"brand {brand} should validate"


# ── normalize_drug_name ──────────────────────────────────────────────────


def test_normalize_lowercases():
    assert normalize_drug_name("TYLENOL") == "tylenol"


def test_normalize_strips_whitespace():
    assert normalize_drug_name("  tylenol  ") == "tylenol"


def test_normalize_canonicalizes_combo_separators():
    """Plus / with / spaced-slash all collapse to plain `/`."""
    assert (
        normalize_drug_name("Acetaminophen + Codeine")
        == "acetaminophen/codeine"
    )
    assert (
        normalize_drug_name("Acetaminophen with Codeine")
        == "acetaminophen/codeine"
    )
    assert (
        normalize_drug_name("Acetaminophen / Codeine")
        == "acetaminophen/codeine"
    )


def test_normalize_collapses_repeated_spaces():
    assert normalize_drug_name("amox  cilin") == "amox cilin"


# ── lookup_drug_class ────────────────────────────────────────────────────


def test_lookup_class_for_generic():
    """Acetaminophen → analgesic_antipyretic."""
    assert lookup_drug_class("acetaminophen") == "analgesic_antipyretic"


def test_lookup_class_for_brand():
    """Brand → generic → class."""
    assert lookup_drug_class("Tylenol") == "analgesic_antipyretic"


def test_lookup_class_for_nsaid_brand():
    """Advil → ibuprofen → nsaid."""
    assert lookup_drug_class("Advil") == "nsaid"


def test_lookup_class_unknown_returns_none():
    assert lookup_drug_class("furbleamabin") is None


# ── resolve_to_generic ──────────────────────────────────────────────────


def test_resolve_brand_to_generic():
    assert resolve_to_generic("Tylenol") == "acetaminophen"


def test_resolve_generic_returns_itself():
    """Already-a-generic input is returned as the canonical lowercase."""
    assert resolve_to_generic("acetaminophen") == "acetaminophen"
    assert resolve_to_generic("ACETAMINOPHEN") == "acetaminophen"


def test_resolve_unknown_returns_none():
    assert resolve_to_generic("furbleamabin") is None


# ── Catalog shape invariants ─────────────────────────────────────────────


def test_catalog_version_stable():
    assert CATALOG_VERSION == "2026-06-01.1"
    assert get_catalog_version() == CATALOG_VERSION


def test_brand_to_generic_all_resolve():
    """Every BRAND_TO_GENERIC value must exist in GENERIC_DRUGS.
    A dangling brand → generic mapping that points at a non-existent
    generic would silently emit `validate_drug=False` for a brand
    that should validate; trap it at curation time."""
    for brand, generic in BRAND_TO_GENERIC.items():
        assert generic in GENERIC_DRUGS, (
            f"brand {brand!r} points at {generic!r}, "
            "which is NOT in GENERIC_DRUGS"
        )


def test_required_post_op_analgesics_present():
    """Pilot specialties (ortho + plastic) lean heavily on these — a
    regression that dropped one would surface as a flood of
    `drug_validated=False` for routine post-op rx."""
    for required in (
        "acetaminophen", "ibuprofen", "naproxen",
        "acetaminophen/codeine", "tramadol",
    ):
        assert required in GENERIC_DRUGS, f"missing required {required}"


def test_required_post_op_antibiotics_present():
    """Cephalexin / cefazolin / clindamycin — ortho post-op staples."""
    for required in ("cephalexin", "cefazolin", "clindamycin", "amoxicillin/clavulanate"):
        assert required in GENERIC_DRUGS, f"missing required {required}"


def test_required_anticoagulants_present():
    """DVT prophylaxis post-op + chronic AC patients."""
    for required in ("enoxaparin", "apixaban", "warfarin"):
        assert required in GENERIC_DRUGS, f"missing required {required}"


def test_total_drugs_reasonable():
    total = total_drugs()
    assert total >= 100, f"catalog too sparse: {total}"
    # Ceiling defends against accidental full-RxNorm inclusion which
    # would defeat the curated-safety design.
    assert total < 10_000, f"catalog suspiciously large: {total}"


def test_class_labels_non_empty():
    for drug, cls in GENERIC_DRUGS.items():
        assert cls.strip(), f"drug {drug} has empty class label"
