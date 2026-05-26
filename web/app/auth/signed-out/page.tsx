"use client";

import Link from "next/link";

export default function SignedOutPage() {
  return (
    <div className="relative flex min-h-screen items-center justify-center bg-navy px-4">
      <div className="rounded-2xl bg-white p-8 text-center shadow-2xl ring-1 ring-white/10">
        <h1 className="mb-2 text-lg font-semibold text-navy-700">Signed out</h1>
        <p className="mb-4 text-sm text-gray-500">
          Your Cognito session has ended.
        </p>
        <Link
          href="/login"
          className="text-sm font-medium text-gold-600 underline hover:text-gold-700"
        >
          Sign in again
        </Link>
      </div>
    </div>
  );
}
