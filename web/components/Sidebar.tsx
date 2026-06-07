"use client";

import {
  Activity,
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CircleUser,
  ClipboardList,
  FileText,
  Film,
  Flag,
  FlaskConical,
  Layers,
  LayoutGrid,
  LogOut,
  Menu,
  ScrollText,
  Settings,
  Search,
  ShieldCheck,
  Users,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import { getMe, logout } from "@/lib/api";
import { getMyProfile } from "@/lib/portal-api";
import type { CurrentUser, UserRole } from "@/types";
import { AurionLogo } from "@/components/AurionLogo";
import LocaleSwitcher from "@/components/portal/LocaleSwitcher";
import ThemeToggle from "@/components/portal/ThemeToggle";
import { useTheme } from "next-themes";

// Mirrors backend require_role() gates per admin router.
// Keep in sync with backend/app/api/v1/admin/*.py and
// backend/app/api/v1/me.py (CLINICIAN-gated portal endpoints).
//
// `tKey` keys into the Sidebar.nav.* namespace in messages/{en,fr}.json
// — adding a new nav entry requires a matching key on both catalogs.
const navigation: {
  tKey: string;
  href: string;
  icon: typeof BarChart3;
  roles: UserRole[];
}[] = [
  // ── Admin / compliance / eval surface (unchanged) ──
  { tKey: "dashboard",  href: "/dashboard", icon: BarChart3,     roles: ["EVAL_TEAM", "ADMIN"] },
  { tKey: "sessions",   href: "/sessions",  icon: Layers,        roles: ["EVAL_TEAM", "ADMIN"] },
  { tKey: "auditLog",   href: "/audit",     icon: ClipboardList, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { tKey: "phiMasking", href: "/masking",   icon: ShieldCheck,   roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { tKey: "users",      href: "/users",     icon: Users,         roles: ["ADMIN"] },
  { tKey: "config",     href: "/config",    icon: Settings,      roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  // Feature flags admin surface (lane-full/card-visibility-flags). ADMIN
  // only — backend's POST /admin/feature-flags writes the AppConfig
  // hosted-version, and the corresponding require_role gate rejects
  // every other role.
  { tKey: "featureFlags", href: "/portal/admin/feature-flags", icon: Flag, roles: ["ADMIN"] },
  // Captured Media (#338) — windowed media-retention review. Visible to the
  // three roles the backend list gate allows (compliance is view-only; the
  // download action is hidden for them in-page). The page itself is also
  // flag-gated (media_review_retention_enabled) and shows a "not enabled"
  // state when the backend 403s.
  { tKey: "capturedMedia", href: "/portal/media", icon: Film, roles: ["COMPLIANCE_OFFICER", "EVAL_TEAM", "ADMIN"] },
  { tKey: "eval",       href: "/eval",      icon: FlaskConical,  roles: ["EVAL_TEAM", "ADMIN"] },
  // ── Clinician portal surface (PR-C onward) ──
  // Admin can preview each portal page for support — backend still
  // 403s admin from POST/PATCH/DELETE on /me/* routes (those are
  // CLINICIAN-only at the dependency layer).
  { tKey: "dashboard",  href: "/portal/dashboard",  icon: BarChart3, roles: ["CLINICIAN"] },
  { tKey: "myNotes",    href: "/portal/notes",      icon: FileText,  roles: ["CLINICIAN", "ADMIN"] },
  { tKey: "templates",  href: "/portal/templates",  icon: LayoutGrid, roles: ["CLINICIAN", "ADMIN"] },
  { tKey: "macros",     href: "/portal/macros",     icon: Zap,       roles: ["CLINICIAN", "ADMIN"] },
  { tKey: "myProfile",  href: "/portal/profile",    icon: CircleUser, roles: ["CLINICIAN", "ADMIN"] },
  // Self-audit log (#162) — clinician-side mirror of /audit. Sits
  // next to My Profile because both are personal-account surfaces.
  // ADMIN previews the page but the backend /me/audit endpoint
  // 403s admin (CLINICIAN-only at the dependency layer), so admins
  // see an empty state — the canonical full audit is /audit.
  { tKey: "myActivity", href: "/portal/audit",      icon: Activity,  roles: ["CLINICIAN", "ADMIN"] },
  // AI Prompts Transparency — read-only catalog of every LLM system
  // prompt the encounter pipeline uses. Sits at the bottom of the
  // clinician nav because it's a reference / audit surface, not part
  // of the everyday workflow.
  { tKey: "aiPrompts",  href: "/portal/prompts",    icon: ScrollText, roles: ["CLINICIAN", "ADMIN"] },
];

/** localStorage key for the desktop sidebar collapsed-state. */
const COLLAPSED_KEY = "aurion-sidebar-collapsed";

export default function Sidebar() {
  const pathname = usePathname();
  const t = useTranslations("Sidebar");
  const tRoles = useTranslations("Roles");
  const tCommon = useTranslations("Common");
  const [mobileOpen, setMobileOpen] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);

  // Desktop collapsed state — persists to localStorage so the choice
  // survives reloads. Initialized to false on the server to avoid
  // hydration mismatch; we read localStorage in an effect and set it
  // once the client mounts.
  const [collapsed, setCollapsed] = useState(false);
  // Theme handle so we can apply the user's stored ui_theme from
  // their profile on first load. next-themes already pulls the
  // last-used value from localStorage, but the backend column is
  // the cross-device source of truth — if the two disagree, the
  // backend wins.
  const { setTheme } = useTheme();

  useEffect(() => {
    let cancelled = false;
    getMe()
      .then((u) => {
        if (!cancelled) setUser(u);
      })
      .catch(() => {
        // 401 already routes to /login via fetchWithAuth; any other failure
        // means the sidebar stays empty rather than showing items the user
        // can't actually open (the backend will 403 those anyway).
      });
    return () => {
      cancelled = true;
    };
  }, []);

  // Read persisted collapsed state on mount.
  useEffect(() => {
    try {
      const stored = window.localStorage.getItem(COLLAPSED_KEY);
      if (stored === "1") setCollapsed(true);
    } catch {
      // Private mode or quota — silently fall back to expanded.
    }
  }, []);

  // Sync theme + locale from the backend on mount (cross-device
  // source of truth). Silent on failure — next-themes already loaded
  // the last-known theme from localStorage; the locale cookie
  // already drove the server-rendered HTML. CLINICIAN-only since
  // admin/eval roles use /admin/users not /profile.
  useEffect(() => {
    if (!user || user.role !== "CLINICIAN") return;
    let cancelled = false;
    getMyProfile()
      .then((p) => {
        if (cancelled) return;
        if (p.ui_theme && ["system", "light", "dark"].includes(p.ui_theme)) {
          setTheme(p.ui_theme);
        }
        // If the backend's stored ui_language disagrees with the
        // cookie that drove this render, fix the cookie + refresh
        // so the chrome catches up. Skip if they agree (avoid an
        // infinite refresh loop). The cookie check is best-effort
        // — server-side cookies() in the layout is authoritative.
        if (
          p.ui_language
          && ["en", "fr"].includes(p.ui_language)
          && !document.cookie.includes(`aurion-locale=${p.ui_language}`)
        ) {
          const oneYear = 60 * 60 * 24 * 365;
          document.cookie =
            `aurion-locale=${p.ui_language}; path=/; max-age=${oneYear}; SameSite=Lax`;
          // Re-render with the new locale. Same router import as
          // LocaleSwitcher; the layout's getLocale() picks up the
          // updated cookie.
          window.location.reload();
        }
      })
      .catch(() => {
        // Profile fetch failed — current theme/locale are fine.
      });
    return () => { cancelled = true; };
  }, [user, setTheme]);

  // Publish the current sidebar width to the document root so the
  // layout's <main> can offset its left padding without prop-drilling
  // the collapsed state. Both values are also in the Tailwind class
  // (lg:w-[68px] / lg:w-64) so this is purely for the content offset.
  useEffect(() => {
    document.documentElement.style.setProperty(
      "--aurion-sidebar-width",
      collapsed ? "68px" : "256px",
    );
  }, [collapsed]);

  const toggleCollapsed = () => {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        window.localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        // Persistence is best-effort.
      }
      return next;
    });
  };

  const visibleNav = user ? navigation.filter((item) => item.roles.includes(user.role)) : [];
  const initial = user?.full_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? "?";

  /** Content layout — shared between the mobile overlay and the
   *  desktop fixed sidebar. `forCollapsed` controls icon-only mode.
   *  We never collapse the mobile overlay (it appears full-width); the
   *  mobile path always passes false. */
  const navContent = (forCollapsed: boolean) => (
    <div className="flex h-full flex-col">
      {/* Brand header — squircle icon (iOS app icon) + Aurion wordmark + role pill.
          In collapsed mode the wordmark + role pill hide; the squircle centers. */}
      <div
        className={
          "flex h-[68px] items-center " +
          (forCollapsed ? "justify-center px-2" : "gap-3 px-5")
        }
      >
        <AurionLogo size={36} />
        {!forCollapsed && (
          <div className="flex items-baseline gap-2">
            <span className="text-[17px] font-semibold tracking-tight text-white">
              Aurion
            </span>
            <span className="rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em] text-gold-300 uppercase">
              {user?.role === "CLINICIAN" ? t("portal") : t("admin")}
            </span>
          </div>
        )}
      </div>

      {/* Hairline */}
      <div
        className={
          "border-t border-white/[0.06] " + (forCollapsed ? "mx-2" : "mx-5")
        }
      />

      {/* Command palette trigger — dispatches a custom window event
          that CommandPalette listens for. In expanded mode this is a
          full-width "Search…" affordance with the ⌘K key hint on
          the right; in collapsed mode it shrinks to the magnifier
          icon, matching the nav link visual rhythm. CLINICIAN only —
          the admin pages don't mount the palette. */}
      {user?.role === "CLINICIAN" && (
        <div
          className={
            "pt-3 " + (forCollapsed ? "px-2" : "px-3")
          }
        >
          <button
            type="button"
            onClick={() => window.dispatchEvent(new Event("aurion:palette:open"))}
            title={forCollapsed ? t("searchTooltip") : undefined}
            aria-label={t("searchTooltip")}
            className={
              "group flex w-full items-center rounded-aurion-md text-[13px] font-medium tracking-tight transition-colors duration-short " +
              (forCollapsed
                ? "justify-center px-2 py-2 text-white/55 hover:bg-white/[0.06] hover:text-white/90"
                : "gap-2.5 border border-white/[0.06] bg-white/[0.03] px-3 py-2 text-white/55 hover:border-white/[0.12] hover:bg-white/[0.06] hover:text-white/85")
            }
          >
            <Search className="h-4 w-4" />
            {!forCollapsed && (
              <>
                <span className="flex-1 text-left">{t("search")}</span>
                <kbd className="inline-flex shrink-0 items-center gap-0.5 rounded-aurion-sm border border-white/[0.08] px-1.5 py-0.5 text-[10px] font-mono text-white/45">
                  ⌘K
                </kbd>
              </>
            )}
          </button>
        </div>
      )}

      {/* Nav links */}
      <nav
        className={
          "sidebar-scroll flex-1 space-y-0.5 overflow-y-auto py-4 " +
          (forCollapsed ? "px-2" : "px-3")
        }
      >
        {visibleNav.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          const label = t(`nav.${item.tKey}` as const);
          return (
            <Link
              // Two clinician + admin nav slots share the same tKey
              // ("dashboard"); distinguish via href so React's diff
              // doesn't reuse the wrong element.
              key={`${item.href}-${item.tKey}`}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              // Native `title` attribute gives free system tooltips
              // in collapsed mode — VoiceOver / NVDA also announce
              // it, so accessibility comes along for the ride.
              title={forCollapsed ? label : undefined}
              aria-label={forCollapsed ? label : undefined}
              className={
                "group relative flex items-center rounded-aurion-md text-[13.5px] font-medium tracking-tight transition-all duration-short ease-aurion " +
                (forCollapsed
                  ? "justify-center px-2 py-2.5"
                  : "gap-3 px-3 py-2.5") +
                " " +
                (isActive
                  ? "bg-white/[0.08] text-white"
                  : "text-white/55 hover:bg-white/[0.04] hover:text-white/85")
              }
            >
              {/* Active indicator — gold rail. */}
              {isActive && (
                <span className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gold-400" />
              )}
              <item.icon
                className={
                  "h-[18px] w-[18px] shrink-0 transition-colors duration-short " +
                  (isActive
                    ? "text-gold-300"
                    : "text-white/40 group-hover:text-white/70")
                }
              />
              {!forCollapsed && label}
            </Link>
          );
        })}
      </nav>

      {/* Hairline */}
      <div
        className={
          "border-t border-white/[0.06] " + (forCollapsed ? "mx-2" : "mx-5")
        }
      />

      {/* User chip + sign-out. */}
      <div className={forCollapsed ? "py-4 px-2" : "px-4 py-4"}>
        <div
          className={
            "flex items-center " + (forCollapsed ? "justify-center" : "gap-3")
          }
        >
          <div
            className="flex h-9 w-9 items-center justify-center rounded-full bg-aurion-gold text-[13px] font-semibold text-navy-700 shadow-gold ring-1 ring-gold-600/30"
            title={forCollapsed ? user?.full_name?.trim() || user?.email || undefined : undefined}
          >
            {initial}
          </div>
          {!forCollapsed && (
            <div className="min-w-0 flex-1">
              <p className="truncate text-[13px] font-medium text-white/90">
                {user?.full_name?.trim() || user?.email || tCommon("loading")}
              </p>
              <p className="truncate text-[11px] text-white/45">
                {user ? tRoles(user.role) : ""}
              </p>
            </div>
          )}
        </div>
        {/* Theme toggle — appears above sign-out in expanded mode so
            the user-related controls cluster together. Hidden in
            collapsed mode (too cramped; theme is accessible from the
            profile page when collapsed). Only renders for CLINICIAN
            since the backend persists via /profile which admin/eval
            don't have. Admin/eval roles see localStorage-only via
            next-themes if they manually toggle from the profile page. */}
        {!forCollapsed && user?.role === "CLINICIAN" && (
          <div className="mt-3 flex flex-col gap-1.5">
            <ThemeToggle variant="compact" />
            <LocaleSwitcher variant="compact" />
          </div>
        )}
        <button
          onClick={logout}
          title={forCollapsed ? t("signOut") : undefined}
          aria-label={forCollapsed ? t("signOut") : undefined}
          className={
            "mt-3 flex items-center rounded-aurion-md text-[13px] text-white/55 transition-colors duration-short hover:bg-white/[0.04] hover:text-white/90 " +
            (forCollapsed
              ? "justify-center w-full px-2 py-2"
              : "w-full gap-2 px-3 py-2")
          }
        >
          <LogOut className="h-4 w-4" />
          {!forCollapsed && t("signOut")}
        </button>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        type="button"
        className="fixed left-4 top-4 z-50 rounded-lg bg-navy p-2 text-gray-300 shadow-lg ring-1 ring-white/10 lg:hidden"
        onClick={() => setMobileOpen(!mobileOpen)}
        aria-label={mobileOpen ? t("mobileMenu.close") : t("mobileMenu.open")}
      >
        {mobileOpen ? (
          <X className="h-5 w-5" />
        ) : (
          <Menu className="h-5 w-5" />
        )}
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden animate-fade-in"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar — mobile (always expanded when open) */}
      <aside
        className={
          "fixed inset-y-0 left-0 z-40 w-64 transform aurion-chrome-navy " +
          "transition-transform duration-aurion ease-aurion lg:hidden " +
          (mobileOpen ? "translate-x-0" : "-translate-x-full")
        }
      >
        {navContent(false)}
      </aside>

      {/* Sidebar — desktop (collapsible). The width transition runs on
          the [width] property; the inner layout reflows via collapsed
          variants. */}
      <aside
        className={
          "hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:flex-col aurion-chrome-navy border-r border-white/[0.04] " +
          "transition-[width] duration-aurion ease-aurion " +
          (collapsed ? "lg:w-[68px]" : "lg:w-64")
        }
      >
        {navContent(collapsed)}
      </aside>

      {/* Collapse toggle — sits on the sidebar's right edge, vertically
          centered. Stays visible in both states so the user can always
          flip back. Hidden on mobile (the hamburger button is the
          mobile control). */}
      <button
        type="button"
        onClick={toggleCollapsed}
        title={collapsed ? t("expand") : t("collapse")}
        aria-label={collapsed ? t("expand") : t("collapse")}
        className={
          "hidden lg:flex items-center justify-center fixed top-[68px] z-50 " +
          "h-6 w-6 rounded-full bg-navy-800 ring-1 ring-white/10 text-white/70 " +
          "shadow-md hover:bg-navy-700 hover:text-white " +
          "transition-[left] duration-aurion ease-aurion " +
          // -translate-x-1/2 keeps the button half-on-half-off the
          // edge, which makes it read as the seam between sidebar
          // and main content rather than as an isolated chrome
          // affordance.
          "-translate-x-1/2 " +
          (collapsed ? "left-[68px]" : "left-64")
        }
      >
        {collapsed ? (
          <ChevronRight className="h-3.5 w-3.5" />
        ) : (
          <ChevronLeft className="h-3.5 w-3.5" />
        )}
      </button>
    </>
  );
}
