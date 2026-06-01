"""Drug catalog validation surface (#58 follow-up).

Validates LLM-emitted drug names against the curated catalog at
extraction time. Mirrors `modules/coding/catalog.py` from #69 — same
three-state contract, same audit-story semantics.

Validation is best-effort: a False result means "not in our curated
catalog" — could still be a real but uncommon drug; the UI surfaces
this as caution-worthy, not as an error. A None result is reserved
for non-prescription order kinds (imaging / lab / referral don't
have a drug field).
"""

from __future__ import annotations

import logging
from typing import Optional

from app.modules.orders.drug_catalog_data import (
    BRAND_TO_GENERIC,
    CATALOG_VERSION,
    GENERIC_DRUGS,
    normalize_drug_name,
)

logger = logging.getLogger("aurion.orders.drug_catalog")


def validate_drug(drug_name: str) -> bool:
    """True when the drug is in our curated catalog (generic OR
    registered brand), False otherwise.

    Always returns a concrete bool — None is reserved for non-
    prescription order kinds and lives in the route/service layer,
    not here.
    """
    normalized = normalize_drug_name(drug_name)
    if not normalized:
        return False
    if normalized in GENERIC_DRUGS:
        return True
    # Try the brand resolution path.
    generic = BRAND_TO_GENERIC.get(normalized)
    if generic and generic in GENERIC_DRUGS:
        return True
    return False


def lookup_drug_class(drug_name: str) -> Optional[str]:
    """Catalog-side class label for the drug (e.g. "nsaid",
    "antibiotic_penicillin"). Useful for pilot analysis of "what
    class is being prescribed across encounters" without exposing
    PHI-adjacent fields in the audit row.

    Returns None for unrecognized drugs.
    """
    normalized = normalize_drug_name(drug_name)
    direct = GENERIC_DRUGS.get(normalized)
    if direct:
        return direct
    generic = BRAND_TO_GENERIC.get(normalized)
    if generic:
        return GENERIC_DRUGS.get(generic)
    return None


def resolve_to_generic(drug_name: str) -> Optional[str]:
    """If the input is a known brand, return the generic. If it's
    already a generic in the catalog, return it as-is. None for
    unknowns.

    The orders service can use this to suggest a generic substitution
    in a future iteration; the foundation slice just validates
    without rewriting."""
    normalized = normalize_drug_name(drug_name)
    if normalized in GENERIC_DRUGS:
        return normalized
    generic = BRAND_TO_GENERIC.get(normalized)
    if generic and generic in GENERIC_DRUGS:
        return generic
    return None


def get_catalog_version() -> str:
    return CATALOG_VERSION
