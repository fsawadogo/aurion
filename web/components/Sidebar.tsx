"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import { useState } from "react";
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
} from "@heroicons/react/24/outline";

const navigation = [
  { name: "Dashboard", href: "/dashboard", icon: ChartBarIcon },
  { name: "Audit Log", href: "/audit", icon: ClipboardDocumentListIcon },
  { name: "Users", href: "/users", icon: UsersIcon },
  { name: "PHI Masking", href: "/masking", icon: ShieldCheckIcon },
  { name: "Config", href: "/config", icon: CogIcon },
  { name: "Sessions", href: "/sessions", icon: RectangleStackIcon },
  { name: "Eval", href: "/eval", icon: BeakerIcon },
];

export default function Sidebar() {
  const pathname = usePathname();
  const [mobileOpen, setMobileOpen] = useState(false);

  const navContent = (
    <div className="flex h-full flex-col">
      {/* Logo */}
      <div className="flex h-16 items-center px-6">
        <span className="text-xl font-bold text-gold">Aurion</span>
        <span className="ml-1.5 text-sm text-gray-400">Admin</span>
      </div>

      {/* Nav links */}
      <nav className="flex-1 space-y-1 px-3 py-4">
        {navigation.map((item) => {
          const isActive = pathname === item.href || pathname?.startsWith(item.href + "/");
          return (
            <Link
              key={item.name}
              href={item.href}
              onClick={() => setMobileOpen(false)}
              className={`group flex items-center gap-3 rounded-lg px-3 py-2.5 text-sm font-medium transition-colors ${
                isActive
                  ? "bg-navy-600 text-gold border-l-[3px] border-gold"
                  : "text-gray-300 hover:bg-navy-600 hover:text-white"
              }`}
            >
              <item.icon className={`h-5 w-5 shrink-0 ${isActive ? "text-gold" : "text-gray-400 group-hover:text-white"}`} />
              {item.name}
            </Link>
          );
        })}
      </nav>

      {/* User info placeholder */}
      <div className="border-t border-navy-600 px-4 py-4">
        <div className="flex items-center gap-3">
          <div className="h-8 w-8 rounded-full bg-gold-600 flex items-center justify-center text-sm font-bold text-navy">
            A
          </div>
          <div className="min-w-0">
            <p className="truncate text-sm font-medium text-white">Admin User</p>
            <p className="truncate text-xs text-gray-400">ADMIN</p>
          </div>
        </div>
      </div>
    </div>
  );

  return (
    <>
      {/* Mobile hamburger */}
      <button
        type="button"
        className="fixed left-4 top-4 z-50 rounded-md bg-navy p-2 text-gray-300 lg:hidden"
        onClick={() => setMobileOpen(!mobileOpen)}
      >
        {mobileOpen ? (
          <XMarkIcon className="h-6 w-6" />
        ) : (
          <Bars3Icon className="h-6 w-6" />
        )}
      </button>

      {/* Mobile overlay */}
      {mobileOpen && (
        <div
          className="fixed inset-0 z-30 bg-black/50 lg:hidden"
          onClick={() => setMobileOpen(false)}
        />
      )}

      {/* Sidebar — mobile */}
      <aside
        className={`fixed inset-y-0 left-0 z-40 w-64 transform bg-navy transition-transform duration-200 lg:hidden ${
          mobileOpen ? "translate-x-0" : "-translate-x-full"
        }`}
      >
        {navContent}
      </aside>

      {/* Sidebar — desktop */}
      <aside className="hidden lg:fixed lg:inset-y-0 lg:left-0 lg:z-40 lg:flex lg:w-64 lg:flex-col bg-navy">
        {navContent}
      </aside>
    </>
  );
}
