"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useState } from "react";
import {
  Bars3Icon,
  XMarkIcon,
  ChartBarIcon,
  ClipboardDocumentListIcon,
  UsersIcon,
  ShieldCheckIcon,
  CogIcon,
  RectangleStackIcon,
  BeakerIcon,
  ArrowRightOnRectangleIcon,
  DocumentTextIcon,
  Squares2X2Icon,
  UserCircleIcon,
} from "@heroicons/react/24/outline";
import { getMe, logout } from "@/lib/api";
import type { CurrentUser, UserRole } from "@/types";
import { AurionLogo } from "@/components/AurionLogo";

// Mirrors backend require_role() gates per admin router.
// Keep in sync with backend/app/api/v1/admin/*.py and
// backend/app/api/v1/me.py (CLINICIAN-gated portal endpoints).
const navigation: {
  name: string;
  href: string;
  icon: typeof ChartBarIcon;
  roles: UserRole[];
}[] = [
  // ── Admin / compliance / eval surface (unchanged) ──
  { name: "Dashboard", href: "/dashboard", icon: ChartBarIcon, roles: ["EVAL_TEAM", "ADMIN"] },
  { name: "Sessions", href: "/sessions", icon: RectangleStackIcon, roles: ["EVAL_TEAM", "ADMIN"] },
  { name: "Audit Log", href: "/audit", icon: ClipboardDocumentListIcon, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { name: "PHI Masking", href: "/masking", icon: ShieldCheckIcon, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { name: "Users", href: "/users", icon: UsersIcon, roles: ["ADMIN"] },
  { name: "Config", href: "/config", icon: CogIcon, roles: ["COMPLIANCE_OFFICER", "ADMIN"] },
  { name: "Eval", href: "/eval", icon: BeakerIcon, roles: ["EVAL_TEAM", "ADMIN"] },
  // ── Clinician portal surface (PR-C onward) ──
  // Admin can preview each portal page for support — backend still
  // 403s admin from POST/PATCH/DELETE on /me/* routes (those are
  // CLINICIAN-only at the dependency layer).
  { name: "Dashboard", href: "/portal/dashboard", icon: ChartBarIcon, roles: ["CLINICIAN"] },
  { name: "My Notes", href: "/portal/notes", icon: DocumentTextIcon, roles: ["CLINICIAN", "ADMIN"] },
  { name: "Templates", href: "/portal/templates", icon: Squares2X2Icon, roles: ["CLINICIAN", "ADMIN"] },
  { name: "My Profile", href: "/portal/profile", icon: UserCircleIcon, roles: ["CLINICIAN", "ADMIN"] },
];

const ROLE_LABEL: Record<UserRole, string> = {
  ADMIN: "Administrator",
  COMPLIANCE_OFFICER: "Compliance Officer",
  EVAL_TEAM: "Eval Team",
  CLINICAL_ADMIN: "Clinical Admin",
  CLINICIAN: "Clinician",
};

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);
  const [user, setUser] = useState<CurrentUser | null>(null);

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

  const visibleNav = user ? navigation.filter((item) => item.roles.includes(user.role)) : [];
  const initial = user?.full_name?.[0]?.toUpperCase() ?? user?.email?.[0]?.toUpperCase() ?? "?";

  const navContent = (
    <div className="flex h-full flex-col">
      {/* Brand header — hex logo + Aurion wordmark + role pill. */}
      <div className="flex h-[68px] items-center gap-3 px-5">
        <AurionLogo size={32} tone="onDark" />
        <div className="flex items-baseline gap-2">
          <span className="text-[17px] font-semibold tracking-tight text-white">
            Aurion
          </span>
          <span className="rounded-md bg-white/[0.08] px-1.5 py-0.5 text-[10px] font-semibold tracking-[0.08em] text-gold-300 uppercase">
            {user?.role === "CLINICIAN" ? "Portal" : "Admin"}
          </span>
        </div>
      </div>

      {/* Hairline */}
      <div className="mx-5 border-t border-white/[0.06]" />

      {/* Nav links */}
      <nav className="sidebar-scroll flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {visibleNav.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          return (
            <Link
              key={item.name}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={
                "group relative flex items-center gap-3 rounded-aurion-md px-3 py-2.5 text-[13.5px] font-medium tracking-tight transition-all duration-short ease-aurion " +
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
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Hairline */}
      <div className="mx-5 border-t border-white/[0.06]" />

      {/* User chip + sign-out. */}
      <div className="px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-9 w-9 items-center justify-center rounded-full bg-aurion-gold text-[13px] font-semibold text-navy-700 shadow-gold/40 ring-1 ring-gold-600/30">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-[13px] font-medium text-white/90">
              {user?.full_name?.trim() || user?.email || "Loading…"}
            </p>
            <p className="truncate text-[11px] text-white/45">
              {user ? ROLE_LABEL[user.role] : ""}
            </p>
          </div>
        </div>
        <button
          onClick={logout}
          className="mt-3 flex w-full items-center gap-2 rounded-aurion-md px-3 py-2 text-[13px] text-white/55 transition-colors duration-short hover:bg-white/[0.04] hover:text-white/90"
        >
          <ArrowRightOnRectangleIcon className="h-4 w-4" />
          Sign out
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
      >
        {mobileOpen ? (
          <XMarkIcon className="h-5 w-5" />
        ) : (
          <Bars3Icon className="h-5 w-5" />
        )}
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/60 backdrop-blur-sm lg:hidden animate-fade-in"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar — mobile */}
      <aside
        className={
          "fixed inset-y-0 left-0 z-40 w-64 transform aurion-chrome-navy " +
          "transition-transform duration-aurion ease-aurion lg:hidden " +
          (mobileOpen ? "translate-x-0" : "-translate-x-full")
        }
      >
        {navContent}
      </aside>

      {/* Sidebar — desktop */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:w-64 lg:flex-col aurion-chrome-navy border-r border-white/[0.04]">
        {navContent}
      </aside>
    </>
  );
}
