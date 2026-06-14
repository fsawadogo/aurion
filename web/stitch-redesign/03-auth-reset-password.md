# Stitch prompt — Reset password (`/reset-password`)

**Generate the "set a new password" screen for the Aurion Clinical AI portal.** Reached from an
emailed reset link (token in URL). Same navy-hero + white card shell.

**Card contents:**
1. Title "Reset password" + subtitle.
2. New-password field (show/hide), Confirm-password field (show/hide), each with inline min-length hint.
3. Primary gold "Reset password" button.
4. Inline validation alert (red) for too-short / mismatch; API error + a friendly contextual hint
   (e.g. "This link expired — request a new one") on separate lines.
5. **Missing-token state:** no form — an error panel ("This reset link is invalid or incomplete") +
   "Back to sign in".

**States:** missing-token (error only) · clean form · submitting · validation error · API error · success (→ sign in).
**Compliance/safety:** never render or echo the token or the user's email.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Palette: canvas `#F5F6FA`, cards `#FFFFFF`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber `#D9941F` / green `#2E9E6A` / red `#D9352B` / blue `#2D6CDF` (never themed). Inter type (tight headings), 16px cards, soft shadow, gold primary button. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.
