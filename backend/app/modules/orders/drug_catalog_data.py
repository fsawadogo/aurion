"""Curated drug catalog for #58 prescription validation.

Pilot scope:
  * common post-op analgesics + antibiotics (the bread-and-butter of
    ortho + plastic surgery prescribing)
  * common chronic-disease drugs (so a physician noting "continues
    metformin" produces a validated row)
  * generic + brand name mapping — the LLM emits either; we accept
    both. The catalog stores GENERIC as the canonical key; brands
    resolve through `_BRAND_TO_GENERIC`

This is NOT a full RxNorm catalog (~250K entries). We deliberately
ship a curated subset for the same reasons as the ICD-10 / E/M / CPT
catalog (#69): pilot relevance, smaller container image, and
`drug_validated=False` reading as "verify before prescribing" rather
than "invalid drug".

Lookup contract: case-insensitive; whitespace-tolerant; matches on
generic OR any registered brand. Combination products
(e.g. "acetaminophen/codeine") use a forward-slash as the canonical
separator; the lookup also accepts " + ", " with ", and
" / ".

Catalog version bumps on curation changes; logged on every
validation run for traceability.
"""

from __future__ import annotations

CATALOG_VERSION = "2026-06-01.1"


# ── Generic drug names ───────────────────────────────────────────────────
#
# Canonical entries — the value is a short class label so the audit
# story shows what TYPE of drug was prescribed (not just the name),
# helpful for pilot analysis of "what gets prescribed across
# encounters."
GENERIC_DRUGS: dict[str, str] = {
    # ── Analgesics — non-opioid ─────────────────────────────────────────
    "acetaminophen": "analgesic_antipyretic",
    "paracetamol": "analgesic_antipyretic",  # international synonym
    "ibuprofen": "nsaid",
    "naproxen": "nsaid",
    "celecoxib": "nsaid_cox2",
    "diclofenac": "nsaid",
    "ketorolac": "nsaid",
    "meloxicam": "nsaid",
    "aspirin": "nsaid_antiplatelet",
    "acetylsalicylic acid": "nsaid_antiplatelet",
    # ── Analgesics — opioid (use cautiously; pilot specialties Rx these) ──
    "codeine": "opioid_weak",
    "tramadol": "opioid_weak",
    "hydrocodone": "opioid_moderate",
    "oxycodone": "opioid_moderate",
    "morphine": "opioid_strong",
    "hydromorphone": "opioid_strong",
    "fentanyl": "opioid_strong",
    "tapentadol": "opioid_moderate",
    # ── Analgesics — combination products ───────────────────────────────
    "acetaminophen/codeine": "combination_analgesic",
    "acetaminophen/oxycodone": "combination_analgesic",
    "acetaminophen/hydrocodone": "combination_analgesic",
    "ibuprofen/famotidine": "combination_analgesic",
    # ── Antibiotics — common ortho + plastic post-op ────────────────────
    "amoxicillin": "antibiotic_penicillin",
    "amoxicillin/clavulanate": "antibiotic_penicillin",
    "cephalexin": "antibiotic_cephalosporin",
    "cefazolin": "antibiotic_cephalosporin",
    "ceftriaxone": "antibiotic_cephalosporin",
    "clindamycin": "antibiotic_lincosamide",
    "doxycycline": "antibiotic_tetracycline",
    "ciprofloxacin": "antibiotic_fluoroquinolone",
    "levofloxacin": "antibiotic_fluoroquinolone",
    "azithromycin": "antibiotic_macrolide",
    "trimethoprim/sulfamethoxazole": "antibiotic_sulfa",
    "metronidazole": "antibiotic_nitroimidazole",
    "vancomycin": "antibiotic_glycopeptide",
    "mupirocin": "antibiotic_topical",
    "bacitracin": "antibiotic_topical",
    "polymyxin b/bacitracin": "antibiotic_topical",
    # ── Anticoagulants / antiplatelets ──────────────────────────────────
    "warfarin": "anticoagulant",
    "apixaban": "anticoagulant_doac",
    "rivaroxaban": "anticoagulant_doac",
    "dabigatran": "anticoagulant_doac",
    "enoxaparin": "anticoagulant_lmwh",
    "heparin": "anticoagulant_heparin",
    "clopidogrel": "antiplatelet",
    # ── Steroids — peri-op + injection ──────────────────────────────────
    "prednisone": "corticosteroid_oral",
    "methylprednisolone": "corticosteroid_oral",
    "dexamethasone": "corticosteroid_oral",
    "triamcinolone": "corticosteroid_injection",
    "betamethasone": "corticosteroid_injection",
    # ── Anti-emetics / GI ───────────────────────────────────────────────
    "ondansetron": "antiemetic",
    "metoclopramide": "antiemetic",
    "promethazine": "antiemetic",
    "omeprazole": "proton_pump_inhibitor",
    "pantoprazole": "proton_pump_inhibitor",
    "esomeprazole": "proton_pump_inhibitor",
    "ranitidine": "h2_blocker",  # withdrawn 2020 but still seen
    "famotidine": "h2_blocker",
    # ── Anesthetic / local ──────────────────────────────────────────────
    "lidocaine": "local_anesthetic",
    "bupivacaine": "local_anesthetic",
    "ropivacaine": "local_anesthetic",
    # ── Chronic disease ─────────────────────────────────────────────────
    "metformin": "antidiabetic_biguanide",
    "insulin glargine": "insulin",
    "insulin aspart": "insulin",
    "insulin lispro": "insulin",
    "lisinopril": "antihypertensive_acei",
    "ramipril": "antihypertensive_acei",
    "losartan": "antihypertensive_arb",
    "amlodipine": "antihypertensive_ccb",
    "metoprolol": "antihypertensive_beta_blocker",
    "atenolol": "antihypertensive_beta_blocker",
    "hydrochlorothiazide": "diuretic",
    "furosemide": "diuretic_loop",
    "atorvastatin": "statin",
    "rosuvastatin": "statin",
    "simvastatin": "statin",
    "levothyroxine": "thyroid_hormone",
    # ── Common psych ────────────────────────────────────────────────────
    "sertraline": "antidepressant_ssri",
    "escitalopram": "antidepressant_ssri",
    "fluoxetine": "antidepressant_ssri",
    "venlafaxine": "antidepressant_snri",
    "duloxetine": "antidepressant_snri",
    "gabapentin": "anticonvulsant_neuropathic",
    "pregabalin": "anticonvulsant_neuropathic",
    "alprazolam": "benzodiazepine",
    "lorazepam": "benzodiazepine",
    "zolpidem": "sedative_hypnotic",
}


# ── Brand → generic mapping ──────────────────────────────────────────────
#
# Common brand names physicians dictate. Resolution flows brand →
# generic → GENERIC_DRUGS for the validated flag. Adding a brand
# requires the generic to already exist in GENERIC_DRUGS.
BRAND_TO_GENERIC: dict[str, str] = {
    # Analgesics
    "tylenol": "acetaminophen",
    "advil": "ibuprofen",
    "motrin": "ibuprofen",
    "aleve": "naproxen",
    "celebrex": "celecoxib",
    "voltaren": "diclofenac",
    "toradol": "ketorolac",
    "mobic": "meloxicam",
    "percocet": "acetaminophen/oxycodone",  # combo brand
    "vicodin": "acetaminophen/hydrocodone",
    "tylenol 3": "acetaminophen/codeine",
    "tylenol #3": "acetaminophen/codeine",
    "duexis": "ibuprofen/famotidine",
    "ultram": "tramadol",
    "oxycontin": "oxycodone",
    "dilaudid": "hydromorphone",
    "nucynta": "tapentadol",
    # Antibiotics
    "amoxil": "amoxicillin",
    "augmentin": "amoxicillin/clavulanate",
    "keflex": "cephalexin",
    "ancef": "cefazolin",
    "rocephin": "ceftriaxone",
    "cleocin": "clindamycin",
    "vibramycin": "doxycycline",
    "cipro": "ciprofloxacin",
    "levaquin": "levofloxacin",
    "zithromax": "azithromycin",
    "bactrim": "trimethoprim/sulfamethoxazole",
    "septra": "trimethoprim/sulfamethoxazole",
    "flagyl": "metronidazole",
    "bactroban": "mupirocin",
    "neosporin": "polymyxin b/bacitracin",
    "polysporin": "polymyxin b/bacitracin",
    # Anticoagulants
    "coumadin": "warfarin",
    "eliquis": "apixaban",
    "xarelto": "rivaroxaban",
    "pradaxa": "dabigatran",
    "lovenox": "enoxaparin",
    "plavix": "clopidogrel",
    # Steroids
    "medrol": "methylprednisolone",
    "decadron": "dexamethasone",
    "kenalog": "triamcinolone",
    "celestone": "betamethasone",
    # Anti-emetics / GI
    "zofran": "ondansetron",
    "reglan": "metoclopramide",
    "phenergan": "promethazine",
    "prilosec": "omeprazole",
    "protonix": "pantoprazole",
    "nexium": "esomeprazole",
    "pepcid": "famotidine",
    # Local anesthetic
    "xylocaine": "lidocaine",
    "marcaine": "bupivacaine",
    "naropin": "ropivacaine",
    # Chronic disease
    "glucophage": "metformin",
    "lantus": "insulin glargine",
    "novolog": "insulin aspart",
    "humalog": "insulin lispro",
    "prinivil": "lisinopril",
    "zestril": "lisinopril",
    "altace": "ramipril",
    "cozaar": "losartan",
    "norvasc": "amlodipine",
    "lopressor": "metoprolol",
    "toprol xl": "metoprolol",
    "tenormin": "atenolol",
    "lasix": "furosemide",
    "lipitor": "atorvastatin",
    "crestor": "rosuvastatin",
    "zocor": "simvastatin",
    "synthroid": "levothyroxine",
    # Psych
    "zoloft": "sertraline",
    "lexapro": "escitalopram",
    "prozac": "fluoxetine",
    "effexor": "venlafaxine",
    "cymbalta": "duloxetine",
    "neurontin": "gabapentin",
    "lyrica": "pregabalin",
    "xanax": "alprazolam",
    "ativan": "lorazepam",
    "ambien": "zolpidem",
}


# Common combination-product separators the LLM may emit. We
# canonicalize to "/" for matching.
_COMBO_SEPARATORS = (" + ", " with ", " / ")


def normalize_drug_name(name: str) -> str:
    """Lowercase + collapse whitespace + canonicalize combination
    separators. Public for use by tests + by the validation entry
    point in catalog.py."""
    n = name.strip().lower()
    for sep in _COMBO_SEPARATORS:
        if sep in n:
            n = n.replace(sep, "/")
    # Collapse multiple spaces to single
    n = " ".join(n.split())
    return n


def total_drugs() -> int:
    """For health/telemetry surfaces — generics + brand aliases."""
    return len(GENERIC_DRUGS) + len(BRAND_TO_GENERIC)
