"""Catalog-validation surface for the coding inference path (#69 follow-up).

Validates LLM-emitted codes against our curated subset of E/M / ICD-10 /
CPT codes. The result is a boolean stored on the row at extraction
time — never recomputed on read (the catalog evolves; the audit story
needs to reflect the catalog state at extraction time).

`validate_code(system, code)` returns None for unknown systems
(defensive — parser already drops these before they reach here, but
the function is import-safe).
"""

from __future__ import annotations

import logging
from typing import Optional

from app.modules.coding.catalog_data import (
    CATALOG_VERSION,
    lookup_cpt,
    lookup_em,
    lookup_icd10,
)

logger = logging.getLogger("aurion.coding.catalog")


def validate_code(code_system: str, code: str) -> Optional[bool]:
    """True when the code is in our curated catalog, False when actively
    not found, None for unknown systems.

    The False / None distinction matters for the UI: None means "we
    didn't even check" (legacy row), False means "we checked and
    nothing matched" (caution-worthy at billing time).
    """
    system = code_system.lower().strip()
    if system == "em":
        return lookup_em(code) is not None
    if system == "icd10":
        return lookup_icd10(code) is not None
    if system == "cpt":
        return lookup_cpt(code) is not None
    return None


def lookup_description(code_system: str, code: str) -> Optional[str]:
    """Catalog-side display name for a code, when known. Useful for
    cross-referencing the LLM's description against the canonical
    one — divergence is signal for the audit story but we don't
    auto-correct (the LLM phrasing may be more contextual)."""
    system = code_system.lower().strip()
    if system == "em":
        return lookup_em(code)
    if system == "icd10":
        return lookup_icd10(code)
    if system == "cpt":
        return lookup_cpt(code)
    return None


def get_catalog_version() -> str:
    return CATALOG_VERSION
