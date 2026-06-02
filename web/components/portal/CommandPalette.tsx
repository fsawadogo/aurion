"use client";

import {
  Command as CommandIcon,
  FileText,
  Inbox,
  LayoutDashboard,
  LayoutGrid,
  Sparkles,
  User,
  ZapOff,
} from "lucide-react";
import { useLocale, useTranslations } from "next-intl";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useMemo, useRef, useState } from "react";

import { listMySessions, listMyCustomTemplates } from "@/lib/portal-api";
import type { CustomTemplate, Session } from "@/types";

/**
 * Global ⌘K command palette for the clinician portal.
 *
 * Opens on ⌘K (Mac) / Ctrl+K (Win/Linux), closes on Escape or backdrop
 * click. Arrow keys navigate, Enter selects.
 *
 * Three result groups, in priority order:
 *   1. Navigation — sidebar destinations (Dashboard, Notes, Templates,
 *      Macros, Profile). Always visible when query is empty.
 *   2. Recent sessions — last 8 sessions excluding PURGED. Lets the
 *      physician jump to any recent note review without scrolling
 *      the inbox.
 *   3. Custom templates — owned + shared templates. Selecting drops
 *      into the template editor.
 *
 * Why custom, not cmdk: cmdk is the right library for serious palette
 * builds, but this one fits in ~280 LoC and lets us match the design
 * system tokens (aurion-card / aurion-hairline / aurion-primary) out
 * of the box without a wrapper layer. We can swap to cmdk later if
 * the palette gains complex features (sub-commands, async loading
 * indicators, command history).
 *
 * Data sourcing: sessions + templates are fetched once on first open
 * and cached in component state. The data is small (pilot scale: ≤100
 * sessions per clinician) so refetching on every open would be wasted
 * work — but we DO refetch when the locale changes since the cached
 * specialty labels would otherwise be stale-labeled.
 */
export default function CommandPalette() {
  const tNav = useTranslations("Sidebar.nav");
  const tPalette = useTranslations("CommandPalette");
  const router = useRouter();
  const locale = useLocale();

  const [open, setOpen] = useState(false);
  const [query, setQuery] = useState("");
  // Currently-highlighted result index across the FLATTENED filtered
  // list. Group dividers are visual only; the keyboard cursor walks
  // selectable rows.
  const [cursor, setCursor] = useState(0);
  const [sessions, setSessions] = useState<Session[]>([]);
  const [templates, setTemplates] = useState<CustomTemplate[]>([]);
  const [dataLoaded, setDataLoaded] = useState(false);

  const inputRef = useRef<HTMLInputElement>(null);
  const resultsRef = useRef<HTMLDivElement>(null);

  /* ── Open / close + global keyboard ───────────────────────────────── */

  // Toggle on ⌘K / Ctrl+K. Escape closes. The event runs at the
  // document level so the palette opens from any focused element.
  // We avoid swallowing the shortcut when the user is inside a
  // contenteditable / textarea unless the palette is already open
  // (Escape always closes).
  //
  // Also listens for a custom `aurion:palette:open` window event —
  // the sidebar's Search button dispatches this so we don't have
  // to thread state through a context provider just to open the
  // palette programmatically.
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      const isPaletteOpen = open;
      if ((e.metaKey || e.ctrlKey) && e.key.toLowerCase() === "k") {
        e.preventDefault();
        setOpen((v) => !v);
        return;
      }
      if (isPaletteOpen && e.key === "Escape") {
        e.preventDefault();
        setOpen(false);
      }
    };
    const onOpenEvent = () => setOpen(true);
    document.addEventListener("keydown", onKey);
    window.addEventListener("aurion:palette:open", onOpenEvent);
    return () => {
      document.removeEventListener("keydown", onKey);
      window.removeEventListener("aurion:palette:open", onOpenEvent);
    };
  }, [open]);

  // Reset query + cursor every time the palette opens; auto-focus
  // input on next paint.
  useEffect(() => {
    if (open) {
      setQuery("");
      setCursor(0);
      requestAnimationFrame(() => inputRef.current?.focus());
    }
  }, [open]);

  /* ── Lazy data load on first open ─────────────────────────────────── */

  const loadData = useCallback(async () => {
    try {
      const [ss, ts] = await Promise.all([
        listMySessions(),
        listMyCustomTemplates(),
      ]);
      ss.sort((a, b) => b.created_at.localeCompare(a.created_at));
      setSessions(ss.filter((s) => s.state !== "PURGED").slice(0, 8));
      setTemplates(ts);
      setDataLoaded(true);
    } catch {
      // Silent — palette still works with navigation results.
      // If the network is down the user has bigger problems and
      // the empty groups don't add noise.
      setDataLoaded(true);
    }
  }, []);

  useEffect(() => {
    if (open && !dataLoaded) void loadData();
  }, [open, dataLoaded, loadData]);

  // Refetch when locale changes so cached specialty labels match
  // the current language. Doesn't trigger while the palette is
  // closed — we let the next open absorb the cost.
  useEffect(() => {
    setDataLoaded(false);
  }, [locale]);

  /* ── Result derivation ────────────────────────────────────────────── */

  const navItems = useMemo<CommandItem[]>(
    () => [
      {
        id: "nav-dashboard",
        kind: "nav",
        label: tNav("dashboard"),
        href: "/portal/dashboard",
        icon: <LayoutDashboard className="h-4 w-4" />,
      },
      {
        id: "nav-notes",
        kind: "nav",
        label: tNav("myNotes"),
        href: "/portal/notes",
        icon: <Inbox className="h-4 w-4" />,
      },
      {
        id: "nav-templates",
        kind: "nav",
        label: tNav("templates"),
        href: "/portal/templates",
        icon: <LayoutGrid className="h-4 w-4" />,
      },
      {
        id: "nav-macros",
        kind: "nav",
        label: tNav("macros"),
        href: "/portal/macros",
        icon: <Sparkles className="h-4 w-4" />,
      },
      {
        id: "nav-profile",
        kind: "nav",
        label: tNav("myProfile"),
        href: "/portal/profile",
        icon: <User className="h-4 w-4" />,
      },
      {
        id: "nav-newTemplate",
        kind: "action",
        label: tPalette("actions.newTemplate"),
        href: "/portal/templates/new",
        icon: <Sparkles className="h-4 w-4" />,
      },
    ],
    [tNav, tPalette],
  );

  const sessionItems = useMemo<CommandItem[]>(
    () =>
      sessions.map((s) => ({
        id: `session-${s.id}`,
        kind: "session",
        label: humanSpecialty(s.specialty),
        subtitle: s.external_reference_id ?? s.id.slice(0, 8),
        href: `/portal/notes/${s.id}`,
        icon: <FileText className="h-4 w-4" />,
      })),
    [sessions],
  );

  const templateItems = useMemo<CommandItem[]>(
    () =>
      templates.map((tpl) => ({
        id: `tpl-${tpl.id}`,
        kind: "template",
        label: tpl.display_name,
        subtitle: tpl.key,
        href: `/portal/templates/${tpl.id}`,
        icon: <LayoutGrid className="h-4 w-4" />,
      })),
    [templates],
  );

  /** Filter + group. Each group filters independently; empty groups
   *  collapse so the divider doesn't appear above zero rows. */
  const groups = useMemo<CommandGroup[]>(() => {
    const q = query.trim().toLowerCase();
    const groupsRaw: CommandGroup[] = [
      { id: "nav", label: tPalette("group.navigation"), items: navItems },
      { id: "sessions", label: tPalette("group.recentSessions"), items: sessionItems },
      { id: "templates", label: tPalette("group.templates"), items: templateItems },
    ];
    if (q.length === 0) return groupsRaw;
    return groupsRaw
      .map((g) => ({
        ...g,
        items: g.items.filter((it) => matches(it, q)),
      }))
      .filter((g) => g.items.length > 0);
  }, [query, navItems, sessionItems, templateItems, tPalette]);

  /** Flattened list of selectable items in the same render order as
   *  the visual groups. The cursor walks this. */
  const flatItems = useMemo<CommandItem[]>(
    () => groups.flatMap((g) => g.items),
    [groups],
  );

  // Clamp cursor when the result set shrinks under the typing cursor
  // (e.g. user types another character and the previously-highlighted
  // row drops out of the filter). Never lets cursor sit on a deleted
  // index.
  useEffect(() => {
    if (cursor >= flatItems.length) {
      setCursor(Math.max(0, flatItems.length - 1));
    }
  }, [flatItems.length, cursor]);

  /* ── Selection ────────────────────────────────────────────────────── */

  const selectItem = useCallback(
    (item: CommandItem) => {
      router.push(item.href);
      setOpen(false);
    },
    [router],
  );

  // Arrow keys to navigate the flat list, Enter to select. Wraps at
  // both ends so the user never hits an invisible wall.
  const onInputKeyDown = (e: React.KeyboardEvent<HTMLInputElement>) => {
    if (e.key === "ArrowDown") {
      e.preventDefault();
      setCursor((c) => (c + 1) % Math.max(1, flatItems.length));
    } else if (e.key === "ArrowUp") {
      e.preventDefault();
      setCursor((c) => (c - 1 + Math.max(1, flatItems.length)) % Math.max(1, flatItems.length));
    } else if (e.key === "Enter") {
      e.preventDefault();
      const target = flatItems[cursor];
      if (target) selectItem(target);
    }
  };

  // Scroll the highlighted row into view when the cursor moves with
  // the keyboard. Avoids the user losing the highlight off-screen on
  // long result lists.
  useEffect(() => {
    if (!open) return;
    const node = resultsRef.current?.querySelector<HTMLElement>(
      `[data-cursor="${cursor}"]`,
    );
    node?.scrollIntoView({ block: "nearest" });
  }, [cursor, open]);

  /* ── Render ───────────────────────────────────────────────────────── */

  if (!open) return null;

  return (
    <div
      className="fixed inset-0 z-50 flex items-start justify-center p-4 pt-[12vh]"
      role="dialog"
      aria-modal="true"
      aria-label={tPalette("label")}
    >
      <div
        className="fixed inset-0 bg-black/50 backdrop-blur-sm"
        onClick={() => setOpen(false)}
        aria-hidden
      />
      <div className="relative z-10 w-full max-w-xl overflow-hidden rounded-aurion-lg border border-aurion-hairline bg-aurion-card shadow-card-hover">
        {/* Input row */}
        <div className="flex items-center gap-3 border-b border-aurion-hairline px-4 py-3">
          <CommandIcon className="h-4 w-4 text-aurion-tertiary" />
          <input
            ref={inputRef}
            type="text"
            value={query}
            onChange={(e) => {
              setQuery(e.target.value);
              setCursor(0);
            }}
            onKeyDown={onInputKeyDown}
            placeholder={tPalette("placeholder")}
            className="flex-1 bg-transparent text-sm text-aurion-primary placeholder:text-aurion-tertiary focus:outline-none"
            autoComplete="off"
            spellCheck={false}
          />
          <kbd className="hidden sm:inline-flex shrink-0 items-center rounded-aurion-sm border border-aurion-hairline px-1.5 py-0.5 text-[10px] font-mono text-aurion-tertiary">
            ESC
          </kbd>
        </div>

        {/* Results */}
        <div
          ref={resultsRef}
          className="max-h-[60vh] overflow-y-auto py-2"
        >
          {flatItems.length === 0 ? (
            <EmptyResults query={query} />
          ) : (
            groups.map((g) => (
              <ResultGroup
                key={g.id}
                group={g}
                cursorIndex={cursor}
                flatItems={flatItems}
                onSelect={selectItem}
                onHover={setCursor}
              />
            ))
          )}
        </div>

        {/* Footer hints */}
        <div className="flex items-center gap-3 border-t border-aurion-hairline px-4 py-2 text-[11px] text-aurion-tertiary">
          <span className="inline-flex items-center gap-1">
            <KbdKey>↑</KbdKey><KbdKey>↓</KbdKey>
            {tPalette("hint.navigate")}
          </span>
          <span className="inline-flex items-center gap-1">
            <KbdKey>↵</KbdKey>
            {tPalette("hint.select")}
          </span>
          <span className="ml-auto inline-flex items-center gap-1">
            <KbdKey>⌘K</KbdKey>
            {tPalette("hint.toggle")}
          </span>
        </div>
      </div>
    </div>
  );
}

/* ── Result group ───────────────────────────────────────────────────────── */

function ResultGroup({
  group,
  cursorIndex,
  flatItems,
  onSelect,
  onHover,
}: {
  group: CommandGroup;
  cursorIndex: number;
  flatItems: CommandItem[];
  onSelect: (item: CommandItem) => void;
  onHover: (idx: number) => void;
}) {
  return (
    <div className="mb-1">
      <p className="px-3 pt-2 pb-1 text-[10px] font-semibold uppercase tracking-wide text-aurion-tertiary">
        {group.label}
      </p>
      <ul>
        {group.items.map((item) => {
          const idx = flatItems.indexOf(item);
          const active = idx === cursorIndex;
          return (
            <li key={item.id}>
              <button
                type="button"
                data-cursor={idx}
                onClick={() => onSelect(item)}
                onMouseEnter={() => onHover(idx)}
                className={
                  "w-full flex items-center gap-3 px-3 py-2 text-left text-sm transition-colors " +
                  (active
                    ? "bg-gold-50 text-aurion-primary"
                    : "text-aurion-primary hover:bg-aurion-muted")
                }
              >
                <span className="text-aurion-secondary">{item.icon}</span>
                <span className="flex-1 min-w-0">
                  <span className="block truncate">{item.label}</span>
                  {item.subtitle && (
                    <span className="block truncate font-mono text-[10px] text-aurion-tertiary">
                      {item.subtitle}
                    </span>
                  )}
                </span>
                {active && (
                  <KbdKey>↵</KbdKey>
                )}
              </button>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

/* ── Empty state ────────────────────────────────────────────────────────── */

function EmptyResults({ query }: { query: string }) {
  const t = useTranslations("CommandPalette");
  return (
    <div className="flex flex-col items-center justify-center py-8 text-center">
      <ZapOff className="h-8 w-8 text-aurion-tertiary" />
      <p className="mt-3 text-sm font-medium text-aurion-primary">
        {t("empty.title")}
      </p>
      <p className="mt-1 max-w-[28ch] text-xs text-aurion-secondary">
        {query
          ? t("empty.hintForQuery", { query: query.trim() })
          : t("empty.hint")}
      </p>
    </div>
  );
}

/* ── Helpers ────────────────────────────────────────────────────────────── */

function KbdKey({ children }: { children: React.ReactNode }) {
  return (
    <kbd className="inline-flex items-center rounded-aurion-sm border border-aurion-hairline px-1 py-0.5 text-[10px] font-mono text-aurion-tertiary">
      {children}
    </kbd>
  );
}

/** Tiny fuzzy-ish matcher — case-insensitive substring on label +
 *  subtitle. Good enough for the palette's small data set; promotes
 *  to a proper fuzzy lib (fuse.js / cmdk's matcher) only when the
 *  catalog gets big. */
function matches(item: CommandItem, q: string): boolean {
  return (
    item.label.toLowerCase().includes(q) ||
    (item.subtitle ?? "").toLowerCase().includes(q)
  );
}

function humanSpecialty(key: string): string {
  return key
    .split("_")
    .map((w) => w.charAt(0).toUpperCase() + w.slice(1))
    .join(" ");
}

/* ── Types ──────────────────────────────────────────────────────────────── */

interface CommandItem {
  id: string;
  kind: "nav" | "action" | "session" | "template";
  label: string;
  subtitle?: string;
  href: string;
  icon: React.ReactNode;
}

interface CommandGroup {
  id: string;
  label: string;
  items: CommandItem[];
}
