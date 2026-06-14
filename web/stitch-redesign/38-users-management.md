# Stitch prompt — User management (`/users`)

**Generate the admin user-management screen** — clinician/admin accounts, roles, MFA, activation,
voice-enrollment, last login. (Currently plain + not localized — bring it to the premium portal
standard AND make all copy translatable EN/FR.)

**Layout (single column):**
1. **Header** — eyebrow, H1 "User management", subtitle, primary gold "Create user" button.
2. **User count line** + a **table:** Name (avatar + display name) · Email · **Role badge**
   (ADMIN / CLINICIAN / EVAL_TEAM / COMPLIANCE_OFFICER — semantic colors) · **Status** (Active green /
   Inactive muted) · **Voice** (enrolled check / not) · Last login (relative) · **Actions** —
   an "MFA: required/optional" toggle button (gold when required) and Activate/Deactivate (deactivate
   confirms).
3. **Create-user modal** — Full name, Email, Role dropdown, Password; Cancel + gold Create.

**States:** loading skeleton · empty · error.
**Compliance/safety:** the MFA toggle shows an explanation ("user must enrol TOTP to sign in");
deactivation warns; keep role/status colors fixed.

---
**Design (apply exactly — see `00-DESIGN-SYSTEM.md`):** Premium, calm, clinical-grade; LIGHT mode; generous whitespace. **Use the existing Aurion logo as a fixed placeholder — never invent, redraw, or recolor it.** Shared collapsible left Sidebar (navy mark + gold-active nav) + top-right notification bell; header = uppercase eyebrow → H1 → subtitle, action right. Palette: canvas `#F5F6FA`, cards `#FFFFFF`, hairline `#E6E9EE`, navy `#0C1B37`, accent gold `#C9A84C` (Create, MFA-required); FIXED semantic amber/green/red/blue for role + status badges (never themed). Inter type; 16px cards + soft shadow; 20px modal; sticky-header table. Bilingual EN/FR. Consistent with the rest of the portal + iOS app.
