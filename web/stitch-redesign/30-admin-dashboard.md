# Stitch prompt — Admin/Eval Dashboard, pilot metrics (`/dashboard`)

**Generate the admin/eval pilot-monitoring dashboard** — the 8 behaviour metrics, daily volume, and
specialty breakdown for the Aurion pilot. (This page is currently plain — elevate it to the premium
portal standard.)

**Layout (single column):**
1. **Header** — eyebrow, H1 "Dashboard", subtitle "Pilot performance overview", a time-window badge
   ("last 14 days").
2. **Summary row** (4 cards, navy-tinted with gold figures): Total sessions · Active clinicians ·
   Avg completeness · Avg citation rate.
3. **"Behaviour metrics"** section — 8 metric cards (4-up): each with metric name, a **status dot**
   (green on-target / amber near / red off), big value, target label, one-line description, and a
   14-day **inline mini bar sparkline**. Metrics: template-section completeness, citation
   traceability, physician edit rate, conflict rate, low-confidence frame rate, stage-1 latency,
   stage-2 latency, session completeness.
4. **Two charts side-by-side:** Daily volume (bar chart, hover count) · By specialty (horizontal bars, top 5).

**States:** shimmer skeletons; per-chart empty states; dismissible red error banner. Read-only.
**Compliance/safety:** metric **targets** and status dots stay in fixed semantic colors.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37` (summary cards), accent gold `#C9A84C` (figures, bars); FIXED semantic green `#2E9E6A`/amber `#D9941F`/red `#D9352B`/blue `#2D6CDF` for status. Inter type; 16px cards + soft shadow; CSS sparklines. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.
