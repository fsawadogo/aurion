# Peritwin rebrand — user-visible surfaces ONLY

**Scope (Faïçal, 2026-07-23): "will only change what users see."** Peritwin
everywhere a human looks; Aurion untouched everywhere a machine looks.
Done already: portal.peritwin.com live (dual-domain, PR #676), portal
metadata + login subtitle (PR #677), admin password flows unaffected.

## Do NOT touch (breaks things, zero user visibility)
- iOS bundle id `com.aurionclinical.physician` (Apple forbids changing it;
  Meta Wearables Dev Center + provisioning + TestFlight keyed to it)
- portal.aurionclinical.com + api-dev.aurionclinical.com domains (Universal
  Links, Meta app-link `/wearables/auth`, iOS baked API base URL)
- Account emails @aurionclinical.com (identities, not branding)
- `X-Aurion-Sha256` response header (real wire contract; the compliance
  footnote MENTIONS it — the mention must keep the real header name)
- Internal names: repo, Terraform `aurion-*`, Secrets Manager `aurion/dev/*`,
  logger names, CSS `aurion-*` tokens, `.aurionFont`, Swift type names
- Email sender domain (Resend @aurionclinical.com) — separate decision;
  peritwin.com has no SPF/DKIM records yet

## P1 — Portal strings (no assets needed) — ~0.5d
EN+FR message sweep, ~13 keys each: Auth.forgotPassword/resetPassword,
AIPrompts (descriptiveModeCallout, systemDefaultHint, "Use Aurion default"),
Profile.description, Account.noteLanguage, TemplatesList.fromNoteHint,
TemplateEditor.aiInstructionsHint, NoteReview.chat.assistantLabel ("Aurion" →
"Peritwin"), VideoImport.description, AdminCompliance.footnote (reword around
the LITERAL `X-Aurion-Sha256` header name — do not rename the header). Update
any specs asserting these strings. tsc + vitest.

## P2 — Portal visuals — blocked on Peritwin logo assets
AurionLogo component SVG (sidebar wordmark + squircle), favicon + PWA icons
in web/public. If no official assets, a typographic "Peritwin" wordmark
placeholder is acceptable for the pilot; swap when brand assets exist.

## P3 — iOS strings + display name — ~1d + rides next TestFlight build
- `CFBundleDisplayName` → "Peritwin" (+ watch app display name)
- Localizable.strings EN+FR (~10 keys ×2): login.appName, setup.autoUpload,
  onboarding.voiceExpl.*, profile.voice*, profile.teamEditor.footer,
  login.firstTimeHint, and **onboarding.biometric.consentText** — consent is
  compliance-flavored wording (Law 25/PIPEDA); brand-name swap only, no
  substantive edits; flag in PR for Faïçal's read.
- App Store Connect app name → "Peritwin" (ASC edit, takes effect with build)
- ONE bundled TestFlight dispatch (internal+external per standing rule — the
  MFi caveat means internal-only if it's a glasses-era build; it is).

## P4 — iOS visuals — blocked on same assets
App icon (+watch icon — remember the empty-AppIcon TestFlight rejection
gotcha), launch screen, in-app wordmark views (Theme.swift brand surfaces).

## Sequencing
P1 now → P2 when assets land → P3+P4 together in one TestFlight build.
Portal deploys are instant; iOS waits for one bundled build (don't burn the
Apple upload quota on brand-only builds — ride the next functional build).
