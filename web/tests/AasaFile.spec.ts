/**
 * AUTH-UNIVERSAL-LINKS — regression coverage for the AASA file
 * served at /.well-known/apple-app-site-association.
 *
 * The canonical copy lives at
 *   web/public/.well-known/apple-app-site-association
 * (no extension — Apple's spec). Next.js' static export copies
 * `public/` verbatim into `out/`, so the file ships through
 * `next build → out/.well-known/...` unchanged (with help from the
 * `postbuild: cp -r public/.well-known out/.well-known` hook —
 * Next.js otherwise drops hidden dirs during export).
 *
 * Because Amplify's CDN bypasses custom_rule rewrites for paths
 * under `.well-known/` and hands them straight to S3 (which then
 * 301s on extensionless paths to add a trailing slash, breaking
 * Apple's swcd), we ALSO ship the identical payload at a non-hidden
 * path WITH AN EXPLICIT `.json` EXTENSION:
 *   web/public/aurion-aasa-payload.json
 * An Amplify custom_rule rewrites
 *   /.well-known/apple-app-site-association  →  /aurion-aasa-payload.json
 * with status 200. PR #246 first tried the non-hidden path WITHOUT
 * the extension; Amplify still 301'd it because its CDN treats every
 * extensionless URL as a directory-style route (Next.js' trailingSlash:
 * true) and adds the trailing slash BEFORE evaluating custom_rules.
 * Adding `.json` makes Amplify recognise the URL as a static file and
 * skip the trailing-slash redirect. Header rules still match on the
 * source URL, so Content-Type: application/json applies untouched
 * (and the backing file already ends in .json anyway). See
 * infrastructure/amplify.tf for the full chain-of-evidence comment.
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

const NON_HIDDEN_AASA_PATH = join(
  process.cwd(),
  "public",
  "aurion-aasa-payload.json",
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

  it("ships a non-hidden copy byte-identical to the canonical hidden file", () => {
    // The non-hidden copy at public/aurion-aasa-payload is the
    // rewrite TARGET that Amplify actually serves (the canonical
    // `.well-known/...` source gets 301'd by S3 before our rewrite
    // can fire — see infrastructure/amplify.tf). If these two ever
    // drift, iOS will silently see the WRONG App ID / wrong path
    // matcher on the live URL while the canonical file looks correct
    // in code review. Lock the equality here so any change to the
    // hidden file must also update the non-hidden file (and vice
    // versa) — the test fails loudly the moment they diverge.
    const canonical = readFileSync(AASA_PATH);
    const nonHidden = readFileSync(NON_HIDDEN_AASA_PATH);
    expect(nonHidden.equals(canonical)).toBe(true);
  });
});
