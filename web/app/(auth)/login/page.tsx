"use client";

import { useState } from "react";
import Button from "@/components/ui/Button";
import { startSignIn } from "@/lib/cognito";

export default function LoginPage() {
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSignIn() {
    setError(null);
    setLoading(true);
    try {
      await startSignIn();
      // startSignIn redirects via window.location; if we get here
      // something went wrong before the redirect.
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not start sign-in");
      setLoading(false);
    }
  }

  return (
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden bg-navy px-4">
      {/* Ambient glow */}
      <div className="pointer-events-none absolute -top-40 left-1/2 h-[500px] w-[600px] -translate-x-1/2 rounded-full bg-gold-500/[0.06] blur-3xl" />
      <div className="pointer-events-none absolute -bottom-32 right-0 h-[400px] w-[400px] rounded-full bg-navy-400/20 blur-3xl" />

      <div className="relative w-full max-w-sm animate-slide-up">
        {/* Logo */}
        <div className="mb-10 text-center">
          <div className="mx-auto mb-4 flex h-12 w-12 items-center justify-center rounded-2xl bg-gradient-to-br from-gold-400 to-gold-600 shadow-lg shadow-gold-500/20">
            <svg width="22" height="22" viewBox="0 0 16 16" fill="none" className="text-navy-900">
              <path d="M8 1L14 4.5V11.5L8 15L2 11.5V4.5L8 1Z" stroke="currentColor" strokeWidth="1.5" fill="none" />
              <circle cx="8" cy="8" r="2.5" fill="currentColor" />
            </svg>
          </div>
          <h1 className="text-2xl font-bold text-gradient-gold">Aurion</h1>
          <p className="mt-1 text-sm text-gray-500">Clinical AI Admin Portal</p>
        </div>

        {/* Card */}
        <div className="rounded-2xl bg-white p-8 shadow-2xl shadow-black/20 ring-1 ring-white/10">
          <h2 className="mb-2 text-lg font-semibold text-navy-700">Sign in</h2>
          <p className="mb-6 text-sm text-gray-500">
            Authenticates via the Aurion Cognito hosted UI. Two-factor
            (TOTP) is required for every sign-in.
          </p>

          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0 text-red-500"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path fillRule="evenodd" d="M8 15A7 7 0 108 1a7 7 0 000 14zm1-4a1 1 0 11-2 0 1 1 0 012 0zm0-3V5a1 1 0 10-2 0v3a1 1 0 102 0z" clipRule="evenodd"/>
              </svg>
              <span>{error}</span>
            </div>
          )}

          <Button
            type="button"
            variant="primary"
            size="lg"
            loading={loading}
            fullWidth
            onClick={handleSignIn}
          >
            Sign in with Cognito
          </Button>
        </div>

        <p className="mt-8 text-center text-xs text-gray-600">
          Aurion Clinical AI &middot; For authorized personnel only
        </p>
      </div>
    </div>
  );
}
