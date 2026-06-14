# Stitch prompt — Account settings (`/portal/profile/account`)

**Generate the account-settings screen** — identity, languages, MFA, sessions, sign-out.

**Layout:** breadcrumb (Profile › Account) + header (H1 "Account settings"). A stack of cards:
1. **Identity** — read-only definition list: Name, Email, Role (role pill).
2. **UI language** — EN / FR switch (active = gold) for the portal interface.
3. **Note output language** — separate EN / FR switch for generated clinical notes (kept distinct
   from UI language on purpose).
4. **Two-factor (MFA)** — a setup card: if not enrolled, a "Set up authenticator" flow (QR + code
   verify); if enrolled, an "Enabled" status with a green check.
5. **Active sessions** — list of signed-in sessions (device/last-seen) with revoke.
6. **Security** — a secondary "Sign out" button.

**States:** loading skeleton · loaded · saving (language) · MFA setup steps · error banner.
**Compliance/safety:** keep UI-language and note-language as two clearly separate controls.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → breadcrumb. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C`; FIXED semantic amber/green/red/blue (never themed). Inter type; 16px cards + soft shadow; gold primary/active; role pills. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.
