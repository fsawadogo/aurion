# Stitch prompt — Sign in (`/login`)

**Generate the sign-in screen for the Aurion Clinical AI portal.** Unauthenticated entry point;
email + password with an optional two-factor (TOTP) step.

**Layout:** split hero — left (or top on mobile) a deep **navy gradient hero** panel showing the
**Aurion full logo lockup** (mark + "Aurion" wordmark + tagline "the gold standard in clinical AI")
with a soft gold glow; right a clean white centered card with the form. Calm, premium, focused.

**Card contents (in order):**
1. Title "Sign in" + one-line subtitle.
2. Optional success toast at top (green, dismissible) — "Password reset — sign in with your new password".
3. Email field; Password field with show/hide eye toggle; "Forgot password?" link (right-aligned).
4. Primary gold "Sign in" button (full width).
5. **2FA variant** (same card, swapped): a single 6-digit code input, "Verify" primary button, and a
   quiet "Back to sign in" link. Email/password are remembered behind the scenes.
6. Error banner (red, alert icon) for invalid credentials / lockout / expired code.

**States:** clean · submitting (button spinner) · MFA-required (form swaps to code) · error · success.
**Compliance/safety:** none beyond auth; keep error copy non-enumerating (don't reveal if an account exists).

---
**Aurion design system — apply exactly (do not invent or restyle):** Premium, clinical-grade, calm — generous whitespace, never flashy. LIGHT mode. **LOGO: use the existing Aurion logo as a fixed placeholder image** (navy squircle + gold "A" comet/star mark; full lockup adds the "Aurion" wordmark + tagline on navy) — do NOT design, redraw, recolor, or replace it. Colors: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, brand navy `#0C1B37`, accent gold `#C9A84C` (primary buttons/active), text-secondary `#6B7280`; FIXED semantic (never themed) amber `#D9941F`, green `#2E9E6A`, red `#D9352B`, blue `#2D6CDF`. Type: Inter, tight-tracked headings (large-title 34/700, title 22/600, body 17, micro 11/600 uppercase eyebrows). Radius cards 16 / buttons 12 / chips 10; soft 2-layer card shadow; gold glow on the primary button. Bilingual EN/FR (flexible widths). Must match the rest of the Aurion portal + iOS app exactly.
