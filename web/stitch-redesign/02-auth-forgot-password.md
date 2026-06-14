# Stitch prompt — Forgot password (`/forgot-password`)

**Generate the "forgot password" screen for the Aurion Clinical AI portal.** Same navy-hero + white
card shell as sign-in.

**Card contents:**
1. Title "Forgot password?" + subtitle ("Enter your email and we'll send a reset link").
2. Single email field + primary gold "Send reset link" button.
3. "Back to sign in" link.
4. **Submitted state** (replaces the form): a green confirmation panel with a mail-check icon —
   "Check your inbox" + body text. Shown identically whether or not the account exists.
5. Transport-error banner (red) only for network/server failures.

**States:** form · submitting · submitted (green confirmation) · transport error.
**Compliance/safety:** account-enumeration defense — never reveal whether the email matched; the
confirmation copy is identical either way.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Palette: canvas `#F5F6FA`, cards `#FFFFFF`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber `#D9941F` / green `#2E9E6A` / red `#D9352B` / blue `#2D6CDF` (never themed). Inter type (tight headings), 16px cards, soft shadow, gold primary button. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.
