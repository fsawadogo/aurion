"""Curated billing code catalog for #69 validation.

Pilot scope:
  * orthopedic surgery (Dr. Marie Gdalevitch)
  * plastic surgery (Dr. Perry Gdalevitch)
  * common comorbidities / general medicine signals likely to come up
    in either practice
  * full E/M family (10 codes)
  * common CPT procedure codes for these specialties

This is NOT the full ~70,000-code ICD-10 catalog. We deliberately
ship a curated subset because:
  * the full catalog vendors at megabytes and would bloat container
    images for codes we never see in pilot
  * `code_validated=False` is meant to read as "verify before billing"
    not "this code is invalid" — a real but rare code that's not
    in our subset triggers a useful warning rather than an error

Updates: when the pilot surfaces a real code that's not in this
catalog, we add it here AND document the addition in the audit
ledger comment block. The catalog version bumps so future analysis
can correlate code_validated flags against the catalog at extraction
time.

Catalog version is logged on every validation run for traceability.
"""

from __future__ import annotations

# Bump this when you add codes. Stored alongside row state is a
# future enhancement; for now we log on every validation call.
CATALOG_VERSION = "2026-06-01.1"


# ── E/M (Evaluation & Management) ────────────────────────────────────────
#
# Office/Outpatient — new (99202-99205) and established (99211-99215)
# patient codes per the 2021 AMA guidelines. Covers virtually every
# office visit at CREOQ.
EM_CODES: dict[str, str] = {
    # New patient
    "99202": "Office visit, new patient, straightforward MDM, 15-29 min",
    "99203": "Office visit, new patient, low MDM, 30-44 min",
    "99204": "Office visit, new patient, moderate MDM, 45-59 min",
    "99205": "Office visit, new patient, high MDM, 60-74 min",
    # Established patient
    "99211": "Office visit, est patient, minimal (often nurse)",
    "99212": "Office visit, est patient, straightforward MDM, 10-19 min",
    "99213": "Office visit, est patient, low MDM, 20-29 min",
    "99214": "Office visit, est patient, moderate MDM, 30-39 min",
    "99215": "Office visit, est patient, high MDM, 40-54 min",
    # Prolonged office (add-on, 2021+)
    "99417": "Prolonged outpatient (each 15 min beyond E/M time)",
}


# ── ICD-10-CM ────────────────────────────────────────────────────────────
#
# Curated for ortho + plastic + likely comorbidities. Codes are listed
# in their non-laterality root form where the LLM is unlikely to emit
# the .9 unspecified variant; specific lateralized codes also included
# when commonly used.
ICD10_CODES: dict[str, str] = {
    # ── Orthopedic — knee / leg ─────────────────────────────────────────
    "M17.0": "Bilateral primary osteoarthritis of knee",
    "M17.10": "Unilateral primary osteoarthritis, unspecified knee",
    "M17.11": "Unilateral primary osteoarthritis, right knee",
    "M17.12": "Unilateral primary osteoarthritis, left knee",
    "M23.20": "Derangement of unspecified meniscus, unspecified knee",
    "M23.301": "Other meniscus derangements, anterior horn medial meniscus, right knee",
    "M23.302": "Other meniscus derangements, anterior horn medial meniscus, left knee",
    "M25.561": "Pain in right knee",
    "M25.562": "Pain in left knee",
    "S83.511A": "Sprain of anterior cruciate ligament of right knee, initial",
    "S83.512A": "Sprain of anterior cruciate ligament of left knee, initial",
    # ── Orthopedic — shoulder ───────────────────────────────────────────
    "M75.101": "Unspecified rotator cuff tear or rupture, right",
    "M75.102": "Unspecified rotator cuff tear or rupture, left",
    "M75.41": "Impingement syndrome of right shoulder",
    "M75.42": "Impingement syndrome of left shoulder",
    "M25.511": "Pain in right shoulder",
    "M25.512": "Pain in left shoulder",
    "S43.401A": "Unspecified sprain of right shoulder joint, initial",
    "S43.402A": "Unspecified sprain of left shoulder joint, initial",
    # ── Orthopedic — hip ────────────────────────────────────────────────
    "M16.11": "Unilateral primary osteoarthritis, right hip",
    "M16.12": "Unilateral primary osteoarthritis, left hip",
    "M25.551": "Pain in right hip",
    "M25.552": "Pain in left hip",
    # ── Orthopedic — back / spine ───────────────────────────────────────
    "M54.5": "Low back pain (deprecated 2021; use M54.50)",
    "M54.50": "Low back pain, unspecified",
    "M54.51": "Vertebrogenic low back pain",
    "M54.59": "Other low back pain",
    "M54.16": "Radiculopathy, lumbar region",
    "M51.27": "Other intervertebral disc displacement, lumbosacral",
    # ── Plastic surgery — wounds / lacerations / skin ───────────────────
    "L91.0": "Hypertrophic scar (keloid)",
    "L90.5": "Scar conditions and fibrosis of skin",
    "S01.81XA": "Laceration without foreign body of other part of head, initial",
    "L72.0": "Epidermal cyst",
    "L72.3": "Sebaceous cyst",
    # ── Plastic surgery — breast / chest wall ───────────────────────────
    "N64.4": "Mastodynia (breast pain)",
    "N60.21": "Fibroadenosis of right breast",
    "N60.22": "Fibroadenosis of left breast",
    "Z90.10": "Acquired absence of unspecified breast and nipple",
    "Z90.11": "Acquired absence of right breast and nipple",
    "Z90.12": "Acquired absence of left breast and nipple",
    # ── Plastic surgery — burns / contractures ──────────────────────────
    "T20.30XA": "Burn of 3rd degree of head, face, neck, initial",
    "T22.30XA": "Burn of 3rd degree of shoulder and upper limb, initial",
    "L98.7": "Excessive and redundant skin and subcutaneous tissue",
    # ── Plastic surgery — congenital / cleft ────────────────────────────
    "Q35.9": "Cleft palate, unspecified",
    "Q36.9": "Cleft lip, unspecified",
    "Q37.9": "Cleft palate with cleft lip, unspecified",
    # ── Common comorbidities ────────────────────────────────────────────
    "E11.9": "Type 2 diabetes mellitus without complications",
    "I10": "Essential (primary) hypertension",
    "E66.9": "Obesity, unspecified",
    "F32.A": "Depression, unspecified",
    "F41.1": "Generalized anxiety disorder",
    "Z79.01": "Long term (current) use of anticoagulants",
    "Z79.4": "Long term (current) use of insulin",
    # ── Generic / unspecified pain ──────────────────────────────────────
    "R52": "Pain, unspecified",
    "G89.18": "Other acute postprocedural pain",
    "G89.28": "Other chronic postprocedural pain",
}


# ── CPT (Current Procedural Terminology) ─────────────────────────────────
#
# Curated for the pilot specialties' common procedures. Real CPT
# catalog is licensed by the AMA; we ship the codes we expect to see
# and treat the rest as "not in catalog" so they get the verify-before-
# billing warning.
CPT_CODES: dict[str, str] = {
    # ── Orthopedic — imaging ────────────────────────────────────────────
    "73721": "MRI of knee without contrast",
    "73722": "MRI of knee with contrast",
    "73723": "MRI of knee without and with contrast",
    "73221": "MRI of upper extremity (e.g. shoulder), without contrast",
    "73222": "MRI of upper extremity, with contrast",
    "73610": "X-ray of ankle, 3+ views",
    "73620": "X-ray of foot, 2 views",
    "72148": "MRI of lumbar spine without contrast",
    "73560": "X-ray of knee, 1 or 2 views",
    "73562": "X-ray of knee, 3 views",
    # ── Orthopedic — injections ─────────────────────────────────────────
    "20610": "Arthrocentesis / injection, major joint",
    "20611": "Arthrocentesis / injection, major joint, ultrasound-guided",
    # ── Orthopedic — common procedures ──────────────────────────────────
    "29881": "Arthroscopy of knee with meniscectomy (medial OR lateral)",
    "29882": "Arthroscopy of knee with meniscus repair",
    "27447": "Total knee arthroplasty",
    "27130": "Total hip arthroplasty",
    "23472": "Total shoulder arthroplasty",
    # ── Plastic surgery — common procedures ─────────────────────────────
    "11400": "Excision benign lesion 0.5 cm or less",
    "11401": "Excision benign lesion 0.6 to 1.0 cm",
    "11402": "Excision benign lesion 1.1 to 2.0 cm",
    "12001": "Simple repair, scalp/neck/extremities, 2.5 cm or less",
    "12002": "Simple repair, scalp/neck/extremities, 2.6 to 7.5 cm",
    "19318": "Breast reduction",
    "19324": "Mammoplasty, augmentation, without prosthetic implant",
    "19325": "Mammoplasty, augmentation, with prosthetic implant",
    "19357": "Breast reconstruction, immediate or delayed, tissue expander",
    "15734": "Muscle, myocutaneous, or fasciocutaneous flap, trunk",
    "14041": "Adjacent tissue transfer/rearrangement, face/lip 10.1-30 cm²",
    "13132": "Repair, complex, forehead/cheek/chin, 2.6 to 7.5 cm",
    # ── E/M-adjacent / observation ──────────────────────────────────────
    "99281": "Emergency department visit, problem-focused",
    "99282": "Emergency department visit, expanded problem-focused",
    "99283": "Emergency department visit, moderate complexity",
    "99284": "Emergency department visit, high complexity",
    "99285": "Emergency department visit, high complexity, threat",
    # ── Anesthesia / pre-op ─────────────────────────────────────────────
    "00400": "Anesthesia for extremity, NOS",
    "01462": "Anesthesia for lower leg cast change",
}


# ── Lookup helpers ───────────────────────────────────────────────────────


def lookup_em(code: str) -> str | None:
    return EM_CODES.get(code.upper().strip())


def lookup_icd10(code: str) -> str | None:
    return ICD10_CODES.get(code.upper().strip())


def lookup_cpt(code: str) -> str | None:
    return CPT_CODES.get(code.upper().strip())


def total_codes() -> int:
    """For health/telemetry surfaces."""
    return len(EM_CODES) + len(ICD10_CODES) + len(CPT_CODES)
