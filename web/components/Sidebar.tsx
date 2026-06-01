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
      {/* Logo */}
      <div className="flex h-16 items-center gap-3 px-6">
        <div className="flex h-8 w-8 items-center justify-center rounded-lg bg-gradient-to-br from-gold-400 to-gold-600 shadow-sm">
          <svg width="16" height="16" viewBox="0 0 16 16" fill="none" className="text-navy-900">
            <path d="M8 1L14 4.5V11.5L8 15L2 11.5V4.5L8 1Z" stroke="currentColor" strokeWidth="1.5" fill="none" />
            <circle cx="8" cy="8" r="2.5" fill="currentColor" />
          </svg>
        </div>
        <div>
          <span className="text-base font-bold text-white tracking-tight">Aurion</span>
          <span className="ml-1.5 rounded bg-navy-600 px-1.5 py-0.5 text-[10px] font-medium text-gold-400 uppercase tracking-wider">
            {user?.role === "CLINICIAN" ? "Portal" : "Admin"}
          </span>
        </div>
      </div>

      {/* Divider */}
      <div className="mx-4 border-t border-white/[0.06]" />

      {/* Nav links */}
      <nav className="sidebar-scroll flex-1 space-y-0.5 overflow-y-auto px-3 py-4">
        {visibleNav.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          return (
            <Link
              key={item.name}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={`group relative flex items-center gap-3 rounded-lg px-3 py-2 text-[13px] font-medium transition-all duration-150 ${
                isActive
                  ? "bg-white/[0.08] text-white"
                  : "text-gray-400 hover:bg-white/[0.04] hover:text-gray-200"
              }`}
            >
              {/* Active indicator bar */}
              {isActive && (
                <div className="absolute left-0 top-1/2 h-5 w-[3px] -translate-y-1/2 rounded-r-full bg-gold-400" />
              )}
              <item.icon className={`h-[18px] w-[18px] shrink-0 transition-colors ${isActive ? "text-gold-400" : "text-gray-500 group-hover:text-gray-300"}`} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* Divider */}
      <div className="mx-4 border-t border-white/[0.06]" />

      {/* User info + sign out */}
      <div className="px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="flex h-8 w-8 items-center justify-center rounded-full bg-gradient-to-br from-gold-400 to-gold-600 text-xs font-bold text-navy-900 shadow-sm">
            {initial}
          </div>
          <div className="min-w-0 flex-1">
            <p className="truncate text-sm font-medium text-white/90">
              {user?.full_name?.trim() || user?.email || "Loading…"}
            </p>
            <p className="truncate text-[11px] text-gray-500">
              {user ? ROLE_LABEL[user.role] : ""}
            </p>
          </div>
        </div>
        <button
          onClick={logout}
          className="mt-3 flex w-full items-center gap-2 rounded-lg px-3 py-2 text-[13px] text-gray-500 transition-colors hover:bg-white/[0.04] hover:text-gray-300"
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

      {/* Sidebar -- mobile */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 transform bg-navy transition-transform duration-200 ease-out lg:hidden ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {navContent}
      </aside>

      {/* Sidebar -- desktop */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:w-64 lg:flex-col bg-navy border-r border-white/[0.06]">
        {navContent}
      </aside>
    </>
  );
}
