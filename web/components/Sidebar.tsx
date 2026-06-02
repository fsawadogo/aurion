"use client";

import {
  BarChart3,
  ChevronLeft,
  ChevronRight,
  CircleUser,
  ClipboardList,
  FileText,
  FlaskConical,
  Layers,
  LayoutGrid,
  LogOut,
  Menu,
  Settings,
  ShieldCheck,
  Users,
  X,
  Zap,
} from "lucide-react";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import { getMe, logout } from "@/lib/api";
import type { CurrentUser, UserRole } from "@/types";
import { AurionLogo } from "@/components/AurionLogo";

// Mirrors backend require_role() gates per admin router.
// Keep in sync with backend/app/api/v1/admin/*.py and
// backend/app/api/v1/me.py (CLINICIAN-gated portal endpoints).
const navigation: {
  name: string;
  href: string;
  icon: typeof BarChart3;
  roles: UserRole[];
}[] = [
  // ── Admin / compliance / eval surface (unchanged) ──
  { name: "Dashboard", href: "/dashboard", icon: BarChart3, roles: ["EVAL_TEAM", "ADMIN"] },
  { name: "Sessions", href: "/sessions", icon: Layers, roles: ["EVAL_TEAM", "ADMIN"] },
  { name: "Audit Log", href: "/audit", icon: ClipboardList, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { name: "PHI Masking", href: "/masking", icon: ShieldCheck, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { name: "Users", href: "/users", icon: Users, roles: ["ADMIN"] },
  { name: "Config", href: "/config", icon: Settings, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { name: "Eval", href: "/eval", icon: FlaskConical, roles: ["EVAL_TEAM", "ADMIN"] },
  // ── Clinician portal surface (PR-C onward) ──
  // Admin can preview each portal page for support — backend still
  // 403s admin from POST/PATCH/DELETE on /me/* routes (those are
  // CLINICIAN-only at the dependency layer).
  { name: "Dashboard", href: "/portal/dashboard", icon: BarChart3, roles: ["CLINICIAN"] },
  { name: "My Notes", href: "/portal/notes", icon: FileText, roles: ["CLINICIAN", "ADMIN"] },
  { name: "Templates", href: "/portal/templates", icon: LayoutGrid, roles: ["CLINICIAN", "ADMIN"] },
  { name: "Macros", href: "/portal/macros", icon: Zap, roles: ["CLINICIAN", "ADMIN"] },
  { name: "My Profile", href: "/portal/profile", icon: CircleUser, roles: ["CLINICIAN", "ADMIN"] },
];

const ROLE_LABEL: Record<UserRole, string> = {
  ADMIN: "Administrator",
  COMPLIANCE_OFFICER: "Compliance Officer",
  EVAL_TEAM: "Eval Team",
  CLINICAL_ADMIN: "Clinical Admin",
  CLINICIAN: "Clinician",
};

/** localStorage key for the desktop sidebar collapsed-state. */
const COLLAPSED_KEY = "aurion-sidebar-collapsed";

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);

  // Desktop collapsed state — persists to localStorage so the choice
  // survives reloads. Initialized to false on the server to avoid
  // hydration mismatch; we read localStorage in an effect and set it
  // once the client mounts.
  const [collapsed, setCollapsed] = useState(false);

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
              {user?.role === "CLINICIAN" ? "Portal" : "Admin"}
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

      {/* Nav links */}
      <nav
        className={
          "sidebar-scroll flex-1 space-y-0.5 overflow-y-auto py-4 " +
          (forCollapsed ? "px-2" : "px-3")
        }
      >
        {visibleNav.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          return (
            <Link
              key={item.name}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              // Native `title` attribute gives free system tooltips
              // in collapsed mode — VoiceOver / NVDA also announce
              // it, so accessibility comes along for the ride.
              title={forCollapsed ? item.name : undefined}
              aria-label={forCollapsed ? item.name : undefined}
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
              {!forCollapsed && item.name}
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
                {user?.full_name?.trim() || user?.email || "Loading…"}
              </p>
              <p className="truncate text-[11px] text-white/45">
                {user ? ROLE_LABEL[user.role] : ""}
              </p>
            </div>
          )}
        </div>
        <button
          onClick={logout}
          title={forCollapsed ? "Sign out" : undefined}
          aria-label={forCollapsed ? "Sign out" : undefined}
          className={
            "mt-3 flex items-center rounded-aurion-md text-[13px] text-white/55 transition-colors duration-short hover:bg-white/[0.04] hover:text-white/90 " +
            (forCollapsed
              ? "justify-center w-full px-2 py-2"
              : "w-full gap-2 px-3 py-2")
          }
        >
          <LogOut className="h-4 w-4" />
          {!forCollapsed && "Sign out"}
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
        aria-label={mobileOpen ? "Close menu" : "Open menu"}
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
        title={collapsed ? "Expand sidebar" : "Collapse sidebar"}
        aria-label={collapsed ? "Expand sidebar" : "Collapse sidebar"}
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
