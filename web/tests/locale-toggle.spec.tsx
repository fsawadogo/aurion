import { describe, it, expect, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import LocaleSwitcher from "@/components/portal/LocaleSwitcher";
import { LOCALE_COOKIE } from "@/i18n/config";
import { withIntl } from "./helpers/intl";

/**
 * LOCALE-TOGGLE — language picker on the account page.
 *
 * The switcher's job is to:
 *   1. Write the `aurion-locale` cookie when the user picks a new locale.
 *   2. Sync the choice to the backend via PUT /me/profile (`ui_language`)
 *      so the choice survives logout + crosses devices.
 *   3. Trigger router.refresh() so the chrome reloads with the new
 *      catalog without a hard reload.
 *
 * We mock the API client at the module boundary and assert the cookie
 * mutation + backend call. router.refresh() is verified via a Next
 * router mock.
 */

vi.mock("@/lib/portal-api", () => ({
  updateMyProfile: vi.fn().mockResolvedValue({}),
}));

const refresh = vi.fn();
vi.mock("next/navigation", () => ({
  useRouter: () => ({ refresh }),
}));

import { updateMyProfile } from "@/lib/portal-api";

describe("LocaleSwitcher", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    // Reset the cookie jar between tests so a previous click doesn't
    // leak state. `expires=...` in the past evicts the named cookie
    // regardless of how it was set.
    document.cookie = `${LOCALE_COOKIE}=; expires=Thu, 01 Jan 1970 00:00:00 GMT; path=/`;
  });

  it("renders both EN + FR options as radio buttons", () => {
    render(withIntl(<LocaleSwitcher />, "en"));
    const en = screen.getByRole("radio", { name: /english/i });
    const fr = screen.getByRole("radio", { name: /français/i });
    expect(en).toBeInTheDocument();
    expect(fr).toBeInTheDocument();
    // EN is the active radio when locale is "en"
    expect(en).toHaveAttribute("aria-checked", "true");
    expect(fr).toHaveAttribute("aria-checked", "false");
  });

  it("writes the aurion-locale cookie when the user picks FR", async () => {
    const user = userEvent.setup();
    render(withIntl(<LocaleSwitcher />, "en"));

    await user.click(screen.getByRole("radio", { name: /français/i }));

    // The cookie should now contain `aurion-locale=fr`. Document.cookie
    // serializes to `key=value; key2=value2` so a substring assert is
    // enough — and matches LocaleProvider's read regex.
    await waitFor(() => {
      expect(document.cookie).toContain(`${LOCALE_COOKIE}=fr`);
    });
  });

  it("syncs the choice to backend via updateMyProfile", async () => {
    const user = userEvent.setup();
    render(withIntl(<LocaleSwitcher />, "en"));

    await user.click(screen.getByRole("radio", { name: /français/i }));

    await waitFor(() => {
      expect(updateMyProfile).toHaveBeenCalledWith({ ui_language: "fr" });
    });
  });

  it("calls router.refresh() after the cookie flip", async () => {
    const user = userEvent.setup();
    render(withIntl(<LocaleSwitcher />, "en"));

    await user.click(screen.getByRole("radio", { name: /français/i }));

    await waitFor(() => {
      expect(refresh).toHaveBeenCalledTimes(1);
    });
  });

  it("skips the backend sync when persistToBackend=false", async () => {
    const user = userEvent.setup();
    render(withIntl(<LocaleSwitcher persistToBackend={false} />, "en"));

    await user.click(screen.getByRole("radio", { name: /français/i }));

    await waitFor(() => {
      expect(document.cookie).toContain(`${LOCALE_COOKIE}=fr`);
    });
    // Cookie + router.refresh() still fire, but the backend PUT is
    // skipped — used on admin chrome pages where the caller has no
    // physician_profiles row.
    expect(updateMyProfile).not.toHaveBeenCalled();
    expect(refresh).toHaveBeenCalledTimes(1);
  });

  it("is a no-op when the user re-clicks the active locale", async () => {
    const user = userEvent.setup();
    render(withIntl(<LocaleSwitcher />, "en"));

    // Re-click the already-active radio — the click handler bails
    // before any side effect runs.
    await user.click(screen.getByRole("radio", { name: /english/i }));

    expect(updateMyProfile).not.toHaveBeenCalled();
    expect(refresh).not.toHaveBeenCalled();
  });

  it("renders inline variant with full language names", () => {
    render(withIntl(<LocaleSwitcher variant="inline" />, "fr"));
    // Inline variant labels show the localized language names; the
    // FR active locale labels itself as "Français".
    const fr = screen.getByRole("radio", { name: /français/i });
    expect(fr).toHaveTextContent("Français");
    expect(fr).toHaveAttribute("aria-checked", "true");
  });
});
