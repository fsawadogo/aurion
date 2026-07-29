## Task

loop-2 — a universal SOAP template in the shared Library, seeded reproducibly:
`backend/starter_library/soap.json` + idempotent `backend/scripts/seed_library.py`
(`is_shared=True`), so every clinician sees SOAP in Templates → Library like the
existing four shared templates.

## Why

Backlog Cohort 6 · loop-2 — "Seed the Library with SOAP … closes 'Localiser
modèle SOAP'" (2026-07-15 weekly, Faïçal). Uzziel 2026-07-29: "create a SOAP
note for global access. Should be in library like the others." Source
structure: Marie's gold S/O/A/P notes (CPO-Brain sandbox — structure only is
reused; no note content, no PHI, nothing from CPO-Brain is committed). Mobile
constraint honoured: a seeded `is_shared` row reaches iOS through the existing
resolution paths with zero client key lists — explicitly preferred over a new
built-in key (which would cost 5 web + 3 iOS files).

## Approach

**`backend/starter_library/soap.json`** — one `Template`-schema JSON:

- `key: "soap_universal"`, `display_name: "SOAP — Universal"`, `version: "1.0"`,
  `detail_level: "standard"` (the general-purpose note should not inherit the
  historical maximalist default — TE-1's middle setting).
- 4 required sections mirroring Marie's gold-note skeleton, titles bilingual
  (EN/FR in one string — custom templates carry a single title; two separate
  language rows would double Library maintenance):
  1. `subjective` · "S — Subjective / Subjectif" — CC in the patient's words,
     HPI, patient-reported history when discussed. Patient-reported only.
  2. `objective` · "O — Objective / Objectif" — observed/measured/reviewed
     only: exam by region as narrated, vitals if stated, imaging (e.g. PACS)
     as described, in-visit procedures. Visual-trigger keywords (spoken
     phrases, per the TE-4 lesson: matched against anchor transcript text) +
     `measurement_output_expected: true` (#63 — ROM/wound metrics land here).
  3. `assessment` · "A — Assessment / Évaluation" — the provider's STATED
     assessment, numbered, attributed ("Provider assessed…"); never inferred.
  4. `plan` · "P — Plan" — management as stated: treatments, restrictions,
     counselling, orders/referrals, follow-up, return precautions.
- No `system_prompt` (structure-only; registry descriptive prompt governs).

**`backend/scripts/seed_library.py`** — idempotent, mirrors `seed_dev.py`
bootstrapping (sys.path shim, async engine session):

- Loads every `*.json` in `backend/starter_library/`.
- Owner: `--owner-email` arg (or `SEED_LIBRARY_OWNER_EMAIL` env); the email
  must resolve to an existing ADMIN/CLINICAL_ADMIN user — seeded rows follow
  the same ownership model as admin-authored shared templates (tpl-04).
- Upsert by key against the SHARED set (`list_shared`): absent → create via
  `svc.create_for_owner(..., is_shared=True)` (inherits schema + caps +
  descriptive-gate validation); present with different content → update the
  row's content/display_name/version in place (owner unchanged); identical →
  skip. Prints created/updated/unchanged per key; exits non-zero on any
  validation failure (a bad starter file must fail loudly, not half-seed).

**Not in this slice:** running the seed against dev happens post-merge (needs
dev DB creds or the admin UI with the same JSON — operator step, documented in
the PR); no web/iOS changes (Library UI already renders shared rows).

## Acceptance criteria

- [ ] AC-1: `starter_library/soap.json` parses as `Template` and passes
  `_validate_custom_template_fields` (test loads the REAL file).
- [ ] AC-2: sections are exactly `subjective, objective, assessment, plan`,
  all `required`, in that order; `objective` carries visual triggers and
  `measurement_output_expected: true`; the other three carry neither.
- [ ] AC-3: seeding twice is idempotent — second run creates nothing and
  updates nothing (unit test over the upsert routine with stubbed session).
- [ ] AC-4: changed starter content → exactly one update, no duplicate row;
  unknown owner email → non-zero exit before any write.
- [ ] AC-5: created rows have `is_shared=True` and validation failures raise
  (not swallowed).
- [ ] AC-6: full `pytest tests/unit/` green; `ruff check app/ scripts/ tests/`
  clean.

## DRY / SOLID check

- **Existing helpers reused**: `Template` schema + `_validate_custom_template_fields`
  + `create_for_owner(is_shared=True)` + `list_shared` (validation and writes
  stay in the service — the script adds NO second validation path);
  `seed_dev.py`'s bootstrap pattern; the tpl-04 ownership model.
- **New helper introduced?**: `seed_library.py`'s `upsert_shared_template()` —
  new because no seeding path exists for shared templates (this IS loop-2);
  kept in the script, not the service (one caller).
- **iOS UI tasks only**: n/a.

## Out of scope

- Applying the seed to dev (operator step post-merge — documented in PR).
- French-only duplicate rows / per-locale template names.
- loop-3 (canonical renderer) and the rest of Cohort 6.
- Retro-fitting the four existing Library templates into starter_library
  (worth doing later so the whole Library is reproducible — noted, separate).

## Test plan (executable)

1. `cd backend && python -m pytest tests/unit/test_seed_library.py -v`
2. `cd backend && python -m pytest tests/unit/ -q` → full suite green
3. `cd backend && python -m ruff check app/ scripts/ tests/` → clean
4. Post-merge (operator): `python scripts/seed_library.py --owner-email <admin>`
   against dev → "created: soap_universal"; rerun → "unchanged"; Library tab
   shows "SOAP — Universal" for a clinician account.

## Security implications

No PHI: the template ships structure + generic guidance only; nothing from
CPO-Brain (source material) is committed. Section guidance is
descriptive-mode-phrased and the (absent) `system_prompt` path stays behind
the existing `validate_user_prompt` gate. Seeded rows are `is_shared=True`
read-only for clinicians (tpl-04 model). The script writes via the validated
service layer — no raw SQL, no new endpoints, audit posture unchanged.
