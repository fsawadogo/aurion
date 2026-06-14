# Stitch prompt — Clinician Dashboard (`/portal/dashboard`)

**Generate the clinician home dashboard for the Aurion Clinical AI portal** — an at-a-glance view of
pending review work, in-flight processing, recent sessions, and live activity.

**Layout (single column, staggered card entrances):**
1. **Header** — eyebrow "PORTAL", H1 "Dashboard", greeting/subtitle, Refresh button (right).
2. **Quick actions row** — 3 buttons: patient-identifier search (opens modal), bulk export, new template.
3. **Stat tiles** (4-up grid → 2-up md): Awaiting review (clock), In progress (spinner), Approved this
   week (badge-check), Custom templates (grid). Each: big number, label, line icon, subtle gold accent.
4. **Two panels side-by-side:** "Awaiting your review" (list of ≤5 sessions: specialty, relative date,
   short session-ID mono chip, state badge, chevron) and "Visual enrichment running" (Stage 1/2 jobs).
5. **Live activity feed** — chronological events (actor · event · time), quiet timeline.
6. **Recent sessions strip** — 6 horizontally-scrolling snap cards (relative time, specialty,
   optional identifier badge, state badge).
7. **Failed-sessions banner** (amber) only if any failed — count + link.

**States:** skeletons while loading; empty states ("No sessions waiting" / "Nothing processing") with line icon + hint; red error banner.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy squircle mark + role-filtered nav, gold active state, ⌘K search) + top-right notification bell; header = uppercase eyebrow → large-title H1 → description, actions right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber `#D9941F`/green `#2E9E6A`/red `#D9352B`/blue `#2D6CDF` (never themed). Inter (large-title 34/700, title 22/600, body 17, micro-11 uppercase eyebrows); 16px cards + soft shadow; gold primary button; status badges = semantic pills. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.
