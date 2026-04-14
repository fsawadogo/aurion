---
name: web-portal-spec
description: >
  Load when working on Phase 9 web portal. Contains full feature descriptions
  for all 7 portal features, role access matrix, Next.js tech stack details,
  build instructions, and what the web portal explicitly does not do.
  Auto-invoked when editing web/ directory or api/v1/admin/ endpoints.
user-invocable: true
---

# Aurion Web Portal Specification

## Purpose

**The web portal is not a second physician client. It is an admin and compliance tool.**

Physicians use the iOS app exclusively. The portal serves compliance officers, clinical administrators, the internal eval team, and the CTO. It calls existing FastAPI admin API endpoints — no new backend required.

---

## Tech Stack

| Component | Technology |
|---|---|
| Framework | Next.js 14+ (App Router, TypeScript) |
| Styling | Tailwind CSS — Aurion brand: `#0D1B3E` navy, `#C9A84C` gold |
| API | Typed calls to FastAPI `/api/v1/admin/*` — same backend, no new services |
| Authentication | AWS Cognito — same user pool as iOS app. JWT in httpOnly cookie. Roles enforced server-side. |
| Deployment | AWS Amplify — connected to `main` branch, auto-deploy on merge |

---

## Repo Structure

```
web/
├── app/
│   ├── (auth)/login/         # Login page
│   ├── dashboard/            # Pilot metrics dashboard
│   ├── audit/                # Audit log viewer
│   ├── masking/              # PHI masking validation report
│   ├── sessions/             # Session completeness dashboard
│   ├── users/                # User management
│   ├── config/               # Provider configuration viewer (read-only)
│   └── eval/                 # Internal eval team interface
├── components/
├── lib/
│   └── api.ts                # Typed API client — calls FastAPI backend
├── types/
├── package.json
└── .env.example
```

---

## Features — Priority Order

Build in this exact sequence. Features 1–4 must be complete before pilot launch.

### Feature 1 — User Management (`/users`)
**Needed before pilot launch. Access: ADMIN only.**

Capabilities:
- Create clinician accounts — name, email, role assignment
- View all accounts with: name, role, enrollment date, voice profile status (enrolled/not enrolled)
- Deactivate accounts — immediate Cognito disable
- Change roles — CLINICIAN, EVAL_TEAM, COMPLIANCE_OFFICER, ADMIN
- Reset access / force re-authentication

FastAPI endpoints required:
- `GET /api/v1/admin/users` — list with filters
- `POST /api/v1/admin/users` — create
- `PATCH /api/v1/admin/users/{id}` — update role or status
- `DELETE /api/v1/admin/users/{id}` — deactivate (soft delete)

### Feature 2 — Audit Log Viewer (`/audit`)
**Needed for compliance sign-off before pilot launch. Access: COMPLIANCE_OFFICER, ADMIN.**

Capabilities:
- Full session lifecycle events per session
- Filter by: clinician, date range, event type, session state
- Session timeline view — all events for a single session in chronological order
- Export to CSV for institutional compliance reports
- Read-only — no editing, no deletion

Key events to surface prominently: consent_confirmed, masking_confirmed, audio_purged, frames_purged, session_purged, provider_config_changed

FastAPI endpoints required:
- `GET /api/v1/admin/audit` — paginated, filterable
- `GET /api/v1/admin/audit/{session_id}` — full session timeline
- `GET /api/v1/admin/audit/export` — CSV download

### Feature 3 — PHI Masking Validation Report (`/masking`)
**Needed for compliance sign-off before pilot launch. Access: COMPLIANCE_OFFICER, ADMIN.**

Capabilities:
- Per-session masking pass/fail status — target: 100% pass rate
- Filter by date range and clinician
- Flag sessions where masking_confirmed was not logged before upload
- Summary view: pass rate across all sessions, trend over pilot duration
- Red alert if any session has masking_confirmed missing

FastAPI endpoints required:
- `GET /api/v1/admin/masking/report` — aggregate + per-session

### Feature 4 — Provider Configuration Viewer (`/config`)
**Needed during pilot. Access: COMPLIANCE_OFFICER, ADMIN.**

Capabilities:
- Current active AppConfig state: provider for each task, model params, feature flags
- Full config change history: who changed what, when, from which version
- **Read-only** — no write access from web UI. Provider switching stays in admin API.
- Visual diff between versions

FastAPI endpoints required:
- `GET /api/v1/admin/config/current` — current AppConfig state
- `GET /api/v1/admin/config/history` — change log

### Feature 5 — Pilot Metrics Dashboard (`/dashboard`)
**Needed during pilot. Access: CLINICAL_ADMIN, EVAL_TEAM, ADMIN.**

Capabilities:
- All 8 pilot metrics displayed per session, per clinician, and in aggregate:
  - Template section completeness (target ≥ 90%)
  - Citation traceability rate (target ≥ 95%)
  - Physician edit rate per section
  - Conflict rate (CONFLICTS / total frame citations)
  - Low confidence frame rate
  - Stage 1 latency (target < 30s) — with alert if > 60s
  - Stage 2 latency (target < 5 min) — with alert if > 10 min
  - Session completeness (all 8 metrics logged: target 100%)
- Time-series charts per metric across pilot duration
- Specialty breakdown: orthopedic vs. plastic surgery
- Clinician breakdown: individual vs. aggregate

FastAPI endpoints required:
- `GET /api/v1/admin/metrics` — aggregate + per-session + per-clinician

### Feature 6 — Session Completeness Dashboard (`/sessions`)
**Needed during pilot. Access: CLINICAL_ADMIN, EVAL_TEAM, ADMIN.**

Capabilities:
- Per-session view: specialty, template, sections populated vs. required, completeness score
- Filter by clinician and specialty
- Sessions below 90% completeness highlighted red
- Drill down into individual session — which sections were empty and why

FastAPI endpoints required:
- `GET /api/v1/admin/sessions` — paginated, filterable
- `GET /api/v1/admin/sessions/{id}/completeness` — section-level detail

### Feature 7 — Eval Team Interface (`/eval`)
**Needed as soon as pilot generates sessions. Access: EVAL_TEAM, ADMIN only.**

Capabilities:
- Secure interface for quality validation of session triads: masked transcript + masked frames + generated note
- Side-by-side view: transcript segments, frame citations, final note sections
- Per-session quality scoring form:
  - Descriptive mode compliance (pass/fail + notes)
  - SOAP completeness (0–5 per section)
  - Citation accuracy (% correct source anchors)
  - Hallucination count (claims not traceable to any source)
- Flag discrepancies — feeds into engineering quality tracking
- **Masked frames only** — no raw video, no raw audio, no patient-identifiable content
- Session assignment: admin assigns sessions to specific eval team members

FastAPI endpoints required:
- `GET /api/v1/admin/eval/sessions` — sessions assigned to current user
- `GET /api/v1/admin/eval/sessions/{id}` — full session triad
- `POST /api/v1/admin/eval/sessions/{id}/score` — submit quality scores

---

## Role Access Matrix

| Feature | COMPLIANCE_OFFICER | CLINICAL_ADMIN | EVAL_TEAM | ADMIN |
|---|---|---|---|---|
| User management | | | | ✓ |
| Audit log viewer | ✓ | | | ✓ |
| PHI masking report | ✓ | | | ✓ |
| Provider config viewer | ✓ | | | ✓ |
| Pilot metrics dashboard | | ✓ | ✓ | ✓ |
| Session completeness | | ✓ | ✓ | ✓ |
| Eval team interface | | | ✓ | ✓ |

---

## Dev Credentials (created by seed_dev.py)

```
admin@aurion.local          password: devpassword   role: ADMIN
compliance@aurion.local     password: devpassword   role: COMPLIANCE_OFFICER
eval@aurion.local           password: devpassword   role: EVAL_TEAM
clinician@aurion.local      password: devpassword   role: CLINICIAN (no portal access)
```

---

## Local Setup

```bash
cd web
cp .env.example .env.local
# Set: NEXT_PUBLIC_API_URL=http://localhost:8000
npm install
npm run dev
# Portal at: http://localhost:3000
```

---

## What the Web Portal Does NOT Do

- Note creation, editing, or approval — iOS only
- Raw session playback — no video or audio access anywhere in the web portal
- Provider switching — read-only config view. Write access via admin API only.
- Patient-facing features — not a patient portal
- Billing or subscription management
- Direct EMR access
- Anything requiring access to unmasked patient data
