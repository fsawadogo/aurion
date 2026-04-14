"use client";

import { ArrowRightOnRectangleIcon } from "@heroicons/react/24/outline";
import { logout } from "@/lib/api";

interface HeaderProps {
  title: string;
  subtitle?: string;
}

export default function Header({ title, subtitle }: HeaderProps) {
  return (
    <header className="sticky top-0 z-20 flex h-16 items-center justify-between border-b border-gray-200 bg-white px-6 lg:pl-8">
      <div>
        <h1 className="text-lg font-semibold text-navy">{title}</h1>
        {subtitle && (
          <p className="text-sm text-gray-500">{subtitle}</p>
        )}
      </div>
      <button
        onClick={logout}
        className="flex items-center gap-2 rounded-lg px-3 py-2 text-sm text-gray-500 transition-colors hover:bg-gray-100 hover:text-navy"
      >
        <ArrowRightOnRectangleIcon className="h-5 w-5" />
        <span className="hidden sm:inline">Sign out</span>
      </button>
    </header>
  );
}
