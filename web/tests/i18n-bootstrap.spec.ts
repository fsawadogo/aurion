import { describe, it, expect } from "vitest";

import {
  DEFAULT_LOCALE,
  isLocale,
  LOCALE_COOKIE,
  SUPPORTED_LOCALES,
  type Locale,
} from "@/i18n/config";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";

/**
 * I18N-BOOTSTRAP — locale resolution + catalog parity.
 *
 * The portal runs under Next.js `output: "export"` so there's no
 * server `getRequestConfig` to assert against — `web/i18n/LocaleProvider.tsx`
 * is the runtime authority. These tests pin down the contract that
 * provider depends on:
 *
 *   1. The supported-locale list matches the catalog keys (so neither
 *      side can drift without the other).
 *   2. The locale-cookie reader resolves cookie → locale per the
 *      spec: cookie present + supported → that locale; cookie missing
 *      or unsupported → DEFAULT_LOCALE.
 *   3. EN ↔ FR catalogs stay in lockstep — every key in one exists in
 *      the other (zero EN-only or FR-only leaves).
 *
 * `Accept-Language` parsing is intentionally not asserted here:
 * client-side cookie reads happen post-hydration; the cookie itself
 * is set by the locale-switcher UI (covered in `locale-toggle.spec`)
 * or by the backend's `ui_language` sync in `Sidebar.tsx`. There is
 * no Accept-Language code path to test under static export.
 */

/* ─ Locale resolution mirrors LocaleProvider.readLocaleCookie ────── */
function resolveLocaleFromCookie(cookie: string): Locale {
  const match = cookie.match(
    new RegExp(`(?:^|; )${LOCALE_COOKIE}=([^;]*)`),
  );
  if (!match) return DEFAULT_LOCALE;
  const raw = decodeURIComponent(match[1]);
  return isLocale(raw) ? raw : DEFAULT_LOCALE;
}

describe("i18n bootstrap — config", () => {
  it("DEFAULT_LOCALE is in SUPPORTED_LOCALES", () => {
    expect(SUPPORTED_LOCALES).toContain(DEFAULT_LOCALE);
  });

  it("supported locales are exactly EN + FR", () => {
    expect(Array.from(SUPPORTED_LOCALES)).toEqual(["en", "fr"]);
  });

  it("isLocale narrows EN + FR", () => {
    expect(isLocale("en")).toBe(true);
    expect(isLocale("fr")).toBe(true);
  });

  it("isLocale rejects unsupported strings + non-strings", () => {
    expect(isLocale("es")).toBe(false);
    expect(isLocale("EN")).toBe(false); // case-sensitive by design
    expect(isLocale("")).toBe(false);
    expect(isLocale(null)).toBe(false);
    expect(isLocale(undefined)).toBe(false);
    expect(isLocale(123)).toBe(false);
  });
});

describe("i18n bootstrap — cookie resolution", () => {
  it("returns DEFAULT_LOCALE when cookie jar is empty", () => {
    expect(resolveLocaleFromCookie("")).toBe(DEFAULT_LOCALE);
  });

  it("returns FR when the cookie is set to fr", () => {
    expect(resolveLocaleFromCookie(`${LOCALE_COOKIE}=fr`)).toBe("fr");
  });

  it("returns EN when the cookie is set to en", () => {
    expect(resolveLocaleFromCookie(`${LOCALE_COOKIE}=en`)).toBe("en");
  });

  it("returns DEFAULT_LOCALE for an unsupported cookie value", () => {
    expect(resolveLocaleFromCookie(`${LOCALE_COOKIE}=es`)).toBe(
      DEFAULT_LOCALE,
    );
  });

  it("returns FR when the cookie appears mid-jar with other cookies", () => {
    expect(
      resolveLocaleFromCookie(
        `theme=dark; ${LOCALE_COOKIE}=fr; sidebar=collapsed`,
      ),
    ).toBe("fr");
  });

  it("returns DEFAULT_LOCALE when the cookie name isn't ours", () => {
    expect(resolveLocaleFromCookie("locale=fr")).toBe(DEFAULT_LOCALE);
  });
});

describe("i18n bootstrap — catalog parity", () => {
  it("EN catalog has the expected top-level namespaces", () => {
    // Sanity check that the 8 newly migrated pages have catalog
    // namespaces present. Drift here means a migrated page would
    // crash on first render.
    const expected = [
      "Sidebar",
      "Locale",
      "Common",
      "Specialties",
      "Macros",
      "NotesList",
      "Profile",
      "Account",
      "TemplatesList",
      "TemplateNew",
      "TemplateDetail",
      "NoteReview",
    ];
    for (const ns of expected) {
      expect(Object.keys(enMessages)).toContain(ns);
    }
  });

  it("EN + FR catalogs are key-for-key identical", () => {
    const enKeys = flattenKeys(enMessages);
    const frKeys = flattenKeys(frMessages);
    const enOnly = enKeys.filter((k) => !frKeys.includes(k));
    const frOnly = frKeys.filter((k) => !enKeys.includes(k));
    expect(enOnly).toEqual([]);
    expect(frOnly).toEqual([]);
  });
});

/** Flatten a nested message object to dot-paths. Strings are leaves;
 *  nested objects recurse. ICU `{count, plural, …}` strings live at
 *  leaf paths just like simple strings. */
function flattenKeys(obj: unknown, prefix = ""): string[] {
  if (typeof obj !== "object" || obj === null) return [prefix];
  const keys: string[] = [];
  for (const [k, v] of Object.entries(obj)) {
    const path = prefix ? `${prefix}.${k}` : k;
    keys.push(...flattenKeys(v, path));
  }
  return keys;
}
