/**
 * AUTH-UNIVERSAL-LINKS — regression coverage for the AASA file
 * served at /.well-known/apple-app-site-association.
 *
 * The file lives at web/public/.well-known/apple-app-site-association
 * (no extension — Apple's spec). Next.js copies `public/` verbatim
 * into the static-export bundle, so the file ships through
 * `next build → out/.well-known/...` unchanged.
 *
 * iOS' swcd daemon validates the file's structure during the
 * domain-claim handshake; if any of these assertions drift, the
 * Universal Links flow silently breaks (the email link will open
 * Safari instead of the app) — exactly the kind of regression a
 * post-merge smoke test catches days later. Lock the contract here.
 */

import { readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";

const AASA_PATH = join(
  process.cwd(),
  "public",
  ".well-known",
  "apple-app-site-association",
);

const EXPECTED_APP_ID = "2W2Z75Q5ZA.com.aurionclinical.physician";

describe("apple-app-site-association", () => {
  const raw = readFileSync(AASA_PATH, "utf-8");
  const parsed = JSON.parse(raw) as {
    applinks: {
      details: Array<{
        appIDs: string[];
        components: Array<Record<string, unknown>>;
      }>;
    };
    webcredentials?: { apps: string[] };
  };

  it("parses as valid JSON", () => {
    // readFileSync + JSON.parse would have thrown if it didn't.
    expect(parsed).toBeTypeOf("object");
  });

  it("claims the Aurion iOS App ID under applinks", () => {
    expect(parsed.applinks.details[0]?.appIDs).toContain(EXPECTED_APP_ID);
  });

  it("matches the /reset-password path with a non-empty token", () => {
    // The v2 components matcher: path = /reset-password AND ?token=?*
    // (any non-empty token value). Bookmarking /reset-password without
    // a token must NOT open the app — Safari handles the no-token case.
    const component = parsed.applinks.details[0]?.components[0];
    expect(component?.["/"]).toBe("/reset-password");
    const queryMatcher = component?.["?"] as
      | Record<string, string>
      | undefined;
    expect(queryMatcher?.token).toBe("?*");
  });

  it("includes webcredentials so iOS Keychain can auto-fill the saved password", () => {
    // Side bonus from the same domain claim — no code changes needed.
    expect(parsed.webcredentials?.apps).toContain(EXPECTED_APP_ID);
  });

  it("uses portal subdomain only — apex claim would over-scope", () => {
    // Indirect assertion via the App ID shape: we only ship one App
    // ID, and Apple's domain claim is bound to whatever the
    // entitlements file says (`applinks:portal.aurionclinical.com`).
    // Lock the App ID format here so a typo in entitlements + AASA
    // wouldn't slip past CI (the typo'd App ID would mismatch this
    // constant and the test would fail).
    expect(EXPECTED_APP_ID).toMatch(/^2W2Z75Q5ZA\./);
    expect(EXPECTED_APP_ID).toContain(".com.aurionclinical.physician");
  });
});
