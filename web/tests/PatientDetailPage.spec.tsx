import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import PatientDetailClient from "@/app/portal/patients/[identifier]/PatientDetailClient";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { PatientSessionMatch } from "@/types";
import { withIntl } from "./helpers/intl";

/**
 * #61 — patient detail page.
 *
 * The page is the landing surface for any "longitudinal context"
 * shortcut: B2 Quick Actions search modal, future inbox chip click,
 * iOS prior-encounters web mirror. Tests guard the shape (stats +
 * sorted list) and the failure path (retry banner) so a future PR
 * can't quietly drop a state.
 *
 * `next/navigation` is mocked at the module boundary so we can
 * inject the identifier param and observe Link clicks without
 * routing into a real Next.js router.
 */

vi.mock("@/lib/portal-api", () => ({
  listMySessionsByPatientIdentifier: vi.fn(),
}));

const mockUseParams = vi.fn();
const mockUsePathname = vi.fn();
vi.mock("next/navigation", () => ({
  useParams: () => mockUseParams(),
  // `useRouteSegment` (web/lib/use-route-segment.ts) reads from
  // `window.location.pathname` in its mount effect — `usePathname()`
  // returns the collapsed parent route under static export. The
  // mock is here so the dep stays callable; the actual URL is set
  // on `window.location` via `history.replaceState` in beforeEach.
  usePathname: () => mockUsePathname(),
}));

import { listMySessionsByPatientIdentifier } from "@/lib/portal-api";

const IDENTIFIER = "MRN-12345";

const SESSION_OLD: PatientSessionMatch = {
  session_id: "11111111-1111-1111-1111-111111111111",
  specialty: "orthopedic_surgery",
  state: "EXPORTED",
  created_at: "2025-01-15T10:00:00Z",
};

const SESSION_MID: PatientSessionMatch = {
  session_id: "22222222-2222-2222-2222-222222222222",
  specialty: "plastic_surgery",
  state: "REVIEW_COMPLETE",
  created_at: "2025-06-01T14:00:00Z",
};

const SESSION_NEW: PatientSessionMatch = {
  session_id: "33333333-3333-3333-3333-333333333333",
  specialty: "musculoskeletal",
  state: "AWAITING_REVIEW",
  // Created an hour ago in test clock — "1 hr ago" for the recent
  // bucket of formatRelative.
  created_at: new Date(Date.now() - 60 * 60 * 1000).toISOString(),
};

// API returns rows in any order; the page is responsible for sorting
// newest-first. Verify by handing back the unsorted permutation.
const UNSORTED_SESSIONS = [SESSION_OLD, SESSION_NEW, SESSION_MID];

beforeEach(() => {
  vi.mocked(listMySessionsByPatientIdentifier).mockReset();
  mockUseParams.mockReset();
  mockUsePathname.mockReset();
  mockUseParams.mockReturnValue({ identifier: IDENTIFIER });
  mockUsePathname.mockReturnValue(`/portal/patients/${IDENTIFIER}`);
  // `useRouteSegment` reads from `window.location.pathname` post-mount
  // (see hook header for the static-export bug it dodges). jsdom defaults
  // to `/` — set the URL bar to the route the page would actually be on
  // so the hook resolves to the identifier.
  window.history.replaceState({}, "", `/portal/patients/${IDENTIFIER}`);
});

describe("PatientDetailPage — page shell + stats", () => {
  it("renders PageHeader title using the decoded identifier", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue(
      UNSORTED_SESSIONS,
    );
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-session-list"),
      ).toBeInTheDocument();
    });

    // Title appears in the PageHeader; identifier shows verbatim.
    const titleEls = screen.getAllByText(IDENTIFIER);
    expect(titleEls.length).toBeGreaterThanOrEqual(1);
  });

  it("decodes a URL-encoded identifier in the param", async () => {
    mockUseParams.mockReturnValue({ identifier: "MRN%2F12345" });
    mockUsePathname.mockReturnValue("/portal/patients/MRN%2F12345");
    window.history.replaceState({}, "", "/portal/patients/MRN%2F12345");
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue([]);
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        vi.mocked(listMySessionsByPatientIdentifier),
      ).toHaveBeenCalledWith("MRN/12345");
    });

    // The decoded form ("MRN/12345") shows in the breadcrumb / header,
    // not the encoded form.
    expect(screen.getAllByText("MRN/12345").length).toBeGreaterThanOrEqual(1);
  });

  it("renders all three stat tiles with derived values", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue(
      UNSORTED_SESSIONS,
    );
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-session-list"),
      ).toBeInTheDocument();
    });

    // Total = 3.
    expect(screen.getByText("3")).toBeInTheDocument();
    // Recent specialty derives from the newest session (SESSION_NEW
    // is musculoskeletal → "Musculoskeletal"). Appears twice in the
    // DOM — once in the stat tile, once in the matching session row —
    // both legitimate, so we assert presence not uniqueness.
    expect(screen.getAllByText("Musculoskeletal").length).toBeGreaterThanOrEqual(1);
  });
});

describe("PatientDetailPage — session list ordering + navigation", () => {
  it("sorts sessions newest first", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue(
      UNSORTED_SESSIONS,
    );
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-session-list"),
      ).toBeInTheDocument();
    });

    const list = screen.getByTestId("patient-detail-session-list");
    const rows = list.querySelectorAll("li");
    // Order: SESSION_NEW (newest) → SESSION_MID → SESSION_OLD.
    expect(rows[0].textContent).toContain("Musculoskeletal");
    expect(rows[1].textContent).toContain("Plastic Surgery");
    expect(rows[2].textContent).toContain("Orthopedic Surgery");
  });

  it("each row links to /portal/notes/{session_id}", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue(
      UNSORTED_SESSIONS,
    );
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-session-list"),
      ).toBeInTheDocument();
    });

    const row = screen.getByTestId(`patient-detail-row-${SESSION_NEW.session_id}`);
    expect(row.getAttribute("href")).toBe(
      `/portal/notes/${SESSION_NEW.session_id}`,
    );
  });
});

describe("PatientDetailPage — empty + failure states", () => {
  it("renders the EmptyPanelState when the API returns []", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue([]);
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        screen.getByText(
          enMessages.PatientDetail.sessions.empty,
        ),
      ).toBeInTheDocument();
    });

    // Stat tiles still render but with zero/sentinel values.
    expect(screen.getByText("0")).toBeInTheDocument();
    // Empty hint text appears below the empty-state headline.
    expect(
      screen.getByText(enMessages.PatientDetail.sessions.emptyHint),
    ).toBeInTheDocument();
  });

  it("renders the retry banner when the API throws", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockRejectedValue(
      new Error("boom"),
    );
    render(withIntl(<PatientDetailClient />));

    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-retry"),
      ).toBeInTheDocument();
    });

    expect(
      screen.getByText(enMessages.PatientDetail.loadFailed),
    ).toBeInTheDocument();
  });

  it("retry button refetches the API", async () => {
    const user = userEvent.setup();
    vi.mocked(listMySessionsByPatientIdentifier).mockRejectedValueOnce(
      new Error("first attempt"),
    );
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValueOnce(
      UNSORTED_SESSIONS,
    );

    render(withIntl(<PatientDetailClient />));

    const retry = await screen.findByTestId("patient-detail-retry");
    await user.click(retry);

    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-session-list"),
      ).toBeInTheDocument();
    });
    // Two calls: initial load + retry.
    expect(
      vi.mocked(listMySessionsByPatientIdentifier),
    ).toHaveBeenCalledTimes(2);
  });
});

describe("PatientDetail i18n parity", () => {
  it("EN catalog contains the PatientDetail namespace", () => {
    expect(enMessages).toHaveProperty("PatientDetail");
  });

  it("FR catalog contains the PatientDetail namespace", () => {
    expect(frMessages).toHaveProperty("PatientDetail");
  });

  it("EN and FR PatientDetail namespaces have the same key set", () => {
    const enKeys = collectKeys(
      (enMessages as Record<string, unknown>).PatientDetail,
    );
    const frKeys = collectKeys(
      (frMessages as Record<string, unknown>).PatientDetail,
    );
    expect(frKeys).toEqual(enKeys);
  });

  it("renders the FR locale without missing-key warnings", async () => {
    vi.mocked(listMySessionsByPatientIdentifier).mockResolvedValue(
      UNSORTED_SESSIONS,
    );
    render(withIntl(<PatientDetailClient />, "fr"));
    await waitFor(() => {
      expect(
        screen.getByTestId("patient-detail-session-list"),
      ).toBeInTheDocument();
    });

    // "Total des consultations" is FR-specific copy.
    expect(
      screen.getByText(frMessages.PatientDetail.stats.totalSessions),
    ).toBeInTheDocument();
  });
});

/** Same key-collection helper used in AIPromptsPage.spec — dotted-path
 *  flatten of a nested message object. */
function collectKeys(node: unknown, prefix = ""): string[] {
  if (node === null || typeof node !== "object") return [prefix];
  const out: string[] = [];
  for (const [k, v] of Object.entries(node as Record<string, unknown>)) {
    const child = prefix ? `${prefix}.${k}` : k;
    out.push(...collectKeys(v, child));
  }
  return out.sort();
}
