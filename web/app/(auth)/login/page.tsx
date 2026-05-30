"use client";

// Native email + password login against the backend's /api/v1/auth/login
// endpoint (backend-signed JWT, stored in the `aurion_token` cookie).
//
// The Cognito hosted-UI path is paused — lib/cognito.ts is intentionally
// left intact and `getToken()` still reads Cognito tokens first, so flipping
// back to hosted UI is a one-component change. Backend `/auth/login` returns
// 404 outside `APP_ENV=local`, which makes this safe to ship: nothing here
// works against a non-local backend.

import { useState } from "react";
import { useRouter } from "next/navigation";
import Button from "@/components/ui/Button";
import { login } from "@/lib/api";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";
const IS_LOCAL =
  API_BASE.includes("localhost") || API_BASE.includes("127.0.0.1");

export default function LoginPage() {
  const router = useRouter();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [showPassword, setShowPassword] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function handleSubmit(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      await login(email.trim().toLowerCase(), password);
      router.push("/dashboard");
      router.refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Sign-in failed";
      // Friendlier surfaces for the two most common local-dev failures.
      if (/Failed to fetch|NetworkError|Load failed/i.test(msg)) {
        setError(
          `Cannot reach the backend at ${API_BASE}. Is \`docker-compose up\` running?`,
        );
      } else if (/401|Invalid email or password/i.test(msg)) {
        setError("Invalid email or password.");
      } else if (/404/i.test(msg)) {
        setError(
          "Backend /auth/login is disabled here (APP_ENV is not 'local'). Point NEXT_PUBLIC_API_URL at a local backend.",
        );
      } else {
        setError(msg.replace(/^Login failed:\s*/, ""));
      }
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
            <svg
              width="22"
              height="22"
              viewBox="0 0 16 16"
              fill="none"
              className="text-navy-900"
            >
              <path
                d="M8 1L14 4.5V11.5L8 15L2 11.5V4.5L8 1Z"
                stroke="currentColor"
                strokeWidth="1.5"
                fill="none"
              />
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
            Use your Aurion email and password.
          </p>

          {error && (
            <div className="mb-4 flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
              <svg
                className="mt-0.5 h-4 w-4 shrink-0 text-red-500"
                viewBox="0 0 16 16"
                fill="currentColor"
              >
                <path
                  fillRule="evenodd"
                  d="M8 15A7 7 0 108 1a7 7 0 000 14zm1-4a1 1 0 11-2 0 1 1 0 012 0zm0-3V5a1 1 0 10-2 0v3a1 1 0 102 0z"
                  clipRule="evenodd"
                />
              </svg>
              <span>{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-gray-500">
                Email
              </span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
                required
                disabled={loading}
                placeholder="you@aurionclinical.com"
                className="block w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 text-sm text-navy-900 shadow-sm placeholder:text-gray-400 focus:border-gold-400 focus:outline-none focus:ring-2 focus:ring-gold-400/20 disabled:opacity-50"
              />
            </label>

            <label className="block">
              <span className="mb-1 block text-xs font-semibold uppercase tracking-wider text-gray-500">
                Password
              </span>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  disabled={loading}
                  className="block w-full rounded-lg border border-gray-200 bg-white px-3 py-2.5 pr-14 text-sm text-navy-900 shadow-sm focus:border-gold-400 focus:outline-none focus:ring-2 focus:ring-gold-400/20 disabled:opacity-50"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-xs font-medium text-gray-400 hover:text-navy-700"
                  tabIndex={-1}
                >
                  {showPassword ? "Hide" : "Show"}
                </button>
              </div>
            </label>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              fullWidth
            >
              Sign in
            </Button>
          </form>

          {IS_LOCAL && (
            <details className="mt-6 rounded-lg bg-gray-50 p-3 text-xs text-gray-600 ring-1 ring-inset ring-gray-200/50">
              <summary className="cursor-pointer font-semibold text-gray-700">
                Local dev credentials
              </summary>
              <ul className="mt-2 space-y-1 font-mono">
                <li>
                  <span className="text-gray-400">ADMIN</span> ·
                  admin@aurionclinical.com / admin
                </li>
                <li>
                  <span className="text-gray-400">CLINICIAN</span> ·
                  perry@creoq.ca / perry
                </li>
                <li>
                  <span className="text-gray-400">CLINICIAN</span> ·
                  marie@creoq.ca / marie
                </li>
                <li>
                  <span className="text-gray-400">COMPLIANCE</span> ·
                  compliance@aurionclinical.com / compliance
                </li>
                <li>
                  <span className="text-gray-400">EVAL</span> ·
                  eval@aurionclinical.com / eval
                </li>
              </ul>
              <p className="mt-2 text-[11px] text-gray-400">
                Seeded by the backend when <code>APP_ENV=local</code>. Cognito
                hosted UI is paused.
              </p>
            </details>
          )}
        </div>

        <p className="mt-8 text-center text-xs text-gray-600">
          Aurion Clinical AI &middot; For authorized personnel only
        </p>
      </div>
    </div>
  );
}
