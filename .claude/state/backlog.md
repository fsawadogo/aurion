# Aurion Autonomous Loop — Backlog

Canonical task list. The driver loop reads top-to-bottom and works the
topmost Active item matching its lane. Format per line:

    - [ ] {ID} {one-line description} — {effort}d — lane: {backend|ios} — {dependencies}

When a task moves through states, the loop edits this file in place:
Active → In flight → Done (or → Blocked on triple failure).

Last seeded: 2026-05-14.

## Active

- [ ] AUR-MP-CROSSCHECK Add MediaPipe as independent second face detector for Apple Vision (pilot follow-up; revisit only if clinical safety committee asks) — 5d — lane: ios — no blockers
- [ ] AUR-DESIGN-NAVY — design decision on canonical navy (#0C1B37 vs #0D1B3E); collapse aurionNavyLegacy once chosen — 0.5d — lane: ios — no blockers
- [ ] Q-05 Consolidate _to_uuid coercion — same idiom now duplicated in note_gen/repository.py, users_repository.py, _helpers.py, admin/_shared.py; promote to core/uuids.py — 0.5d — lane: backend — no blockers
- [ ] Q-06 _DevUser dataclass — replace Pydantic BaseModel with frozen dataclass for the auth.py seed dict (no I/O, no validation needed) — 0.5d — lane: backend — no blockers

## In flight

(no active in-flight tasks)

## Blocked

(driver moves items here after 3 failed fix attempts; appends reason)

## Done

- [x] Q-04 SessionUIState shim cleanup — 1d — lane: ios — merged: 2026-05-19 (commit 69b317e)
- [x] Q-03 write_audit kwarg whitelist + strict-mode — 1d — lane: backend — merged: 2026-05-19 (commit d539a57)
- [x] Q-02 privacy.py _purge_session_prefix extraction + latent bug fix — 1d — lane: backend — merged: 2026-05-19 (commit ec3a318)
- [x] Q-01 AuditEventType StrEnum — 2d — lane: backend — merged: 2026-05-19 (commit 5c26052)
- [x] M-04-MP MediaPipe face-detection cross-check verification — 1d — lane: ios — merged: 2026-05-19 (commit ca938d0)
- [x] P0-07 E2E smoke test — 3d — lane: backend — merged: 2026-05-19 (commit 3835704)
- [x] M-07-DASH Dashboard Stage 2 tile — 3d — lane: ios — merged: 2026-05-18 (commit 7f024fa)
- [x] B-08 Eval persistence — 3d — lane: backend — merged: 2026-05-18 (commit pending)
- [x] P0-06 Persistent users + admin refactor — 8d — lane: backend — merged: 2026-05-18 (commit e7a5a90)
- [x] P0-04 Alembic migrations — 8d — lane: backend — merged: 2026-05-17 (commit e330675)
- [x] CQR-1 Backend route helpers DRY (Phase 1) — lane: backend — merged: 2026-05-17 (commit e330675)
- [x] CQR-2 utcnow + NoteVersion repository (Phase 2) — lane: backend — merged: 2026-05-17 (commit e330675)
- [x] CQR-3 iOS multipart dedup + Theme legacy navy (Phase 3) — lane: ios — merged: 2026-05-18 (commit f3c147d)
- [x] CQR-4 admin.py package split + SessionUIState enum (Phase 4) — lane: both — merged: 2026-05-18 (commit 9edfef8)

---

## Notes

### Dependency rules
- A task with `depends on X` cannot be picked by `/next-task` until X is in Done.
- `/next-task` skips dependency-blocked items and picks the next unblocked one.
- If no unblocked Active items exist for a lane, the loop pauses and posts
  to `alerts.md` rather than failing.

### Lane assignment
- `lane: backend` — touches `backend/**`, `infrastructure/**`, or migrations.
- `lane: ios` — touches `ios/**` or `demo/**`.
- Vertical slices (both at once) get tagged with the larger lane and stay
  sequential. The remaining backlog items are deliberately split so no
  vertical slice is needed.

### Effort estimates
Mirror the complexity scale in §10 of `AURION-CODING-WORKFLOW.md`:
S=1d, M=3d, L=8d, XL=15d. These are conservative for a single developer
or a single autonomous lane. Override only with prior-spike data.

### Acceptance criteria
Acceptance criteria are NOT pre-written here — `/plan-task` writes them
on the feature branch as the first commit. This file is the menu, not
the recipe.
