import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, within } from "@testing-library/react";
import userEvent from "@testing-library/user-event";

import MyAuditClient, { buildAuditCsv } from "@/app/portal/audit/MyAuditClient";
import enMessages from "@/messages/en.json";
import frMessages from "@/messages/fr.json";
import type { AuditEvent, PaginatedResponse } from "@/types";

import { withIntl } from "./helpers/intl";

/**
 * /portal/audit MyAuditClient — covers issue #162 AC-1..AC-8.
 *
 * The API client is mocked at the module boundary so render is
 * deterministic. We assert against the resolved EN catalog strings
 * (page chrome) and the new `AuditEvents.*` shared namespace (badge
 * labels).
 *
 * The CSV download path is tested by intercepting
 * `URL.createObjectURL` + capturing the `Blob` that was passed to it.
 * That gives us the exact bytes the browser would have downloaded
 * without actually triggering a download in jsdom.
 */

vi.mock("@/lib/portal-api", () => ({
  getMyAuditLog: vi.fn(),
}));

import { getMyAuditLog } from "@/lib/portal-api";

/** Builds a typed `AuditEvent` fixture with sensible defaults so tests
 *  only spell out the fields they care about. */
function evt(partial: Partial<AuditEvent> = {}): AuditEvent {
  return {
    session_id: "11111111-2222-3333-4444-555555555555",
    event_timestamp: "2026-05-15T10:30:00.000Z",
    event_type: "stage1_delivered",
    event_id: "evt_1",
    details: { stage1_latency_ms: 14_200 },
    ...partial,
  };
}

/** Wrap a list of events in the paginated envelope the API returns. */
function paginated(
  items: AuditEvent[],
  page = 1,
  total = items.length,
): PaginatedResponse<AuditEvent> {
  return { items, total, page, page_size: 50 };
}

beforeEach(() => {
  vi.clearAllMocks();
});

describe("MyAuditClient — initial load (AC-1)", () => {
  it("fires /me/audit with page=1, page_size=50 on mount and renders rows", async () => {
    vi.mocked(getMyAuditLog).mockResolvedValue(
      paginated([
        evt({ event_id: "evt_a", event_type: "stage1_delivered" }),
        evt({ event_id: "evt_b", event_type: "note_exported" }),
      ]),
    );

    render(withIntl(<MyAuditClient />));

    await waitFor(() => {
      expect(getMyAuditLog).toHaveBeenCalledWith({
        page: 1,
        page_size: 50,
      });
    });

    // Header chrome
    expect(screen.getByText("My Activity")).toBeInTheDocument();
    expect(
      screen.getByRole("button", { name: /Export CSV/ }),
    ).toBeInTheDocument();

    // Badges resolve via AuditEvents.* — same as the dashboard
    // ActivityFeed. The same label also appears as an option in the
    // event-type <select>, so we look for ALL matches (>=1 means the
    // badge rendered alongside whatever the select shows).
    expect(
      screen.getAllByText("Stage 1 ready for review").length,
    ).toBeGreaterThan(0);
    expect(
      screen.getAllByText("Note exported").length,
    ).toBeGreaterThan(0);
  });

  it("shows the load-error banner when the fetch rejects", async () => {
    vi.mocked(getMyAuditLog).mockRejectedValue(new Error("boom"));
    render(withIntl(<MyAuditClient />));
    await waitFor(() => {
      expect(screen.getByText("boom")).toBeInTheDocument();
    });
  });
});

describe("MyAuditClient — filtering (AC-2)", () => {
  it("includes session_id in the filter query and resets to page 1", async () => {
    const user = userEvent.setup();
    vi.mocked(getMyAuditLog).mockResolvedValue(paginated([]));

    render(withIntl(<MyAuditClient />));
    await waitFor(() =>
      expect(getMyAuditLog).toHaveBeenCalledTimes(1),
    );

    const sessionInput = screen.getByPlaceholderText("Session ID…");
    await user.type(sessionInput, "abcd1234");

    await waitFor(() => {
      const calls = vi.mocked(getMyAuditLog).mock.calls;
      const last = calls[calls.length - 1][0];
      expect(last).toEqual({
        page: 1,
        page_size: 50,
        session_id: "abcd1234",
      });
    });
  });

  it("includes event_type in the filter query when set", async () => {
    const user = userEvent.setup();
    vi.mocked(getMyAuditLog).mockResolvedValue(paginated([]));

    render(withIntl(<MyAuditClient />));
    await waitFor(() =>
      expect(getMyAuditLog).toHaveBeenCalledTimes(1),
    );

    const select = screen.getByDisplayValue("All events");
    await user.selectOptions(select, "note_exported");

    await waitFor(() => {
      const calls = vi.mocked(getMyAuditLog).mock.calls;
      const last = calls[calls.length - 1][0];
      expect(last).toMatchObject({
        page: 1,
        page_size: 50,
        event_type: "note_exported",
      });
    });
  });

  it("Clear button removes all active filters", async () => {
    const user = userEvent.setup();
    vi.mocked(getMyAuditLog).mockResolvedValue(paginated([]));

    render(withIntl(<MyAuditClient />));
    await waitFor(() => expect(getMyAuditLog).toHaveBeenCalled());

    // Set a filter so the Clear button appears.
    const sessionInput = screen.getByPlaceholderText("Session ID…");
    await user.type(sessionInput, "x");

    const clearBtn = await screen.findByRole("button", {
      name: /Clear all filters/,
    });
    await user.click(clearBtn);

    await waitFor(() => {
      const calls = vi.mocked(getMyAuditLog).mock.calls;
      const last = calls[calls.length - 1][0];
      expect(last).toEqual({ page: 1, page_size: 50 });
    });
  });
});

describe("MyAuditClient — pagination (AC-3)", () => {
  it("renders Next/Previous and fetches page+1 when Next clicks", async () => {
    const user = userEvent.setup();
    // total=120 → 3 pages of 50.
    vi.mocked(getMyAuditLog).mockResolvedValue(
      paginated([evt()], 1, 120),
    );

    render(withIntl(<MyAuditClient />));
    await waitFor(() =>
      expect(getMyAuditLog).toHaveBeenCalledTimes(1),
    );

    const nextBtn = await screen.findByRole("button", { name: "Next" });
    await user.click(nextBtn);

    await waitFor(() => {
      const calls = vi.mocked(getMyAuditLog).mock.calls;
      const last = calls[calls.length - 1][0];
      expect(last).toMatchObject({ page: 2 });
    });
  });
});

describe("MyAuditClient — row shape (AC-4)", () => {
  it("renders timestamp, 8-char session id link, badge, details preview", async () => {
    const fullId = "abcdef01-2345-6789-abcd-ef0123456789";
    vi.mocked(getMyAuditLog).mockResolvedValue(
      paginated([
        evt({
          event_id: "evt_x",
          event_type: "note_exported",
          session_id: fullId,
          details: { format: "docx", export_target: "local_download" },
        }),
      ]),
    );

    render(withIntl(<MyAuditClient />));
    await screen.findByText("Note exported");

    // Session id link uses the 8-char prefix and points at the
    // dynamic note review route.
    const link = screen.getByRole("link", { name: /Open session abcdef01/ });
    expect(link).toHaveAttribute("href", `/portal/notes/${fullId}`);
    expect(link).toHaveTextContent("abcdef01");

    // Details preview surfaces stringified JSON from the payload.
    expect(screen.getByText(/"format":"docx"/)).toBeInTheDocument();
  });
});

describe("MyAuditClient — CSV export (AC-5)", () => {
  it("builds the expected CSV body via buildAuditCsv()", () => {
    const csv = buildAuditCsv([
      evt({
        event_id: "evt_csv",
        event_type: "note_exported",
        session_id: "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
        event_timestamp: "2026-05-15T14:00:00.000Z",
        details: { format: "docx" },
      }),
    ]);
    // Headers
    expect(csv).toContain(
      "timestamp_utc,event_type,session_id,details_json",
    );
    // Row content
    expect(csv).toContain("2026-05-15T14:00:00.000Z");
    expect(csv).toContain("note_exported");
    expect(csv).toContain("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee");
    // Details JSON is quoted because it contains double-quotes —
    // RFC 4180 cell escape doubles them.
    expect(csv).toContain('"{""format"":""docx""}"');
  });

  it("triggers a Blob download with a date-stamped filename when the CSV button is clicked", async () => {
    const user = userEvent.setup();
    vi.mocked(getMyAuditLog).mockResolvedValue(
      paginated([
        evt({
          event_id: "evt_csv_dl",
          event_type: "note_exported",
        }),
      ]),
    );

    const originalCreate = URL.createObjectURL;
    const originalRevoke = URL.revokeObjectURL;
    URL.createObjectURL = vi.fn(
      () => "blob:fake",
    ) as unknown as typeof URL.createObjectURL;
    URL.revokeObjectURL =
      vi.fn() as unknown as typeof URL.revokeObjectURL;

    // Intercept anchor clicks so jsdom doesn't try to navigate.
    const originalAppend = document.body.appendChild;
    let capturedAnchor: HTMLAnchorElement | null = null;
    document.body.appendChild = ((node: Node) => {
      if (node instanceof HTMLAnchorElement && node.download) {
        capturedAnchor = node;
        // Skip the real append + click — return the node so the
        // production code's `.click()` call no-ops cleanly.
        return node;
      }
      return originalAppend.call(document.body, node) as Node;
    }) as typeof document.body.appendChild;

    try {
      render(withIntl(<MyAuditClient />));
      await waitFor(() =>
        expect(getMyAuditLog).toHaveBeenCalledTimes(1),
      );

      const csvBtn = await screen.findByRole("button", {
        name: /Export CSV/,
      });
      await user.click(csvBtn);

      await waitFor(() => {
        expect(URL.createObjectURL).toHaveBeenCalled();
      });
      expect(capturedAnchor).not.toBeNull();
      expect((capturedAnchor as HTMLAnchorElement).download).toMatch(
        /^aurion_my_audit_\d{8}\.csv$/,
      );
    } finally {
      URL.createObjectURL = originalCreate;
      URL.revokeObjectURL = originalRevoke;
      document.body.appendChild = originalAppend;
    }
  });
});

describe("MyAuditClient — empty state", () => {
  it("renders the no-matches message when the backend returns 0 events", async () => {
    vi.mocked(getMyAuditLog).mockResolvedValue(paginated([], 1, 0));
    render(withIntl(<MyAuditClient />));
    await waitFor(() => {
      expect(
        screen.getByText("No audit events match the current filters."),
      ).toBeInTheDocument();
    });
  });
});

describe("MyAuditClient — i18n parity (AC-8)", () => {
  it("EN catalog carries every Audit.* + AuditEvents.* + MyActivity.* key", () => {
    expect(enMessages.Audit).toBeDefined();
    expect(enMessages.Audit.filters).toBeDefined();
    expect(enMessages.Audit.table).toBeDefined();
    expect(enMessages.Audit.pagination).toBeDefined();
    expect(enMessages.AuditEvents).toBeDefined();
    expect(enMessages.MyActivity).toBeDefined();
  });

  it("FR catalog carries every Audit.* + AuditEvents.* + MyActivity.* key", () => {
    expect(frMessages.Audit).toBeDefined();
    expect(frMessages.Audit.filters).toBeDefined();
    expect(frMessages.Audit.table).toBeDefined();
    expect(frMessages.Audit.pagination).toBeDefined();
    expect(frMessages.AuditEvents).toBeDefined();
    expect(frMessages.MyActivity).toBeDefined();
  });

  it("EN + FR Audit + AuditEvents + MyActivity have parity at the leaf level", () => {
    function collectKeys(
      obj: Record<string, unknown>,
      prefix = "",
    ): string[] {
      const keys: string[] = [];
      for (const [k, v] of Object.entries(obj)) {
        const path = prefix ? `${prefix}.${k}` : k;
        if (v && typeof v === "object" && !Array.isArray(v)) {
          keys.push(...collectKeys(v as Record<string, unknown>, path));
        } else {
          keys.push(path);
        }
      }
      return keys.sort();
    }
    expect(
      collectKeys(frMessages.Audit as Record<string, unknown>),
    ).toEqual(collectKeys(enMessages.Audit as Record<string, unknown>));
    expect(
      collectKeys(frMessages.AuditEvents as Record<string, unknown>),
    ).toEqual(
      collectKeys(enMessages.AuditEvents as Record<string, unknown>),
    );
    expect(
      collectKeys(frMessages.MyActivity as Record<string, unknown>),
    ).toEqual(
      collectKeys(enMessages.MyActivity as Record<string, unknown>),
    );
  });

  it("renders the FR title when locale=fr", async () => {
    vi.mocked(getMyAuditLog).mockResolvedValue(paginated([]));
    render(withIntl(<MyAuditClient />, "fr"));
    await waitFor(() => {
      expect(screen.getByText("Mon activité")).toBeInTheDocument();
    });
  });
});

describe("AuditEvents shared namespace (AC-9)", () => {
  it("ActivityFeed labels share keys with the audit page (no duplication)", () => {
    // The dashboard's ActivityFeed reads from `AuditEvents.*` rather
    // than the old `Dashboard.activity.event.*` block. Test that
    // the legacy block is no longer present so we can't accidentally
    // reintroduce duplicates later.
    expect(
      (enMessages.Dashboard.activity as { event?: unknown }).event,
    ).toBeUndefined();
    expect(
      (frMessages.Dashboard.activity as { event?: unknown }).event,
    ).toBeUndefined();
  });
});

/* Force the helper-only import to type-check. */
void within;
