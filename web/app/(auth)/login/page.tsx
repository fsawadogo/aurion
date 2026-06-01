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
import {
  EyeIcon,
  EyeSlashIcon,
  ExclamationCircleIcon,
  LockClosedIcon,
} from "@heroicons/react/24/outline";

import Button from "@/components/ui/Button";
import { AurionLogoLockup } from "@/components/AurionLogo";
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
      const auth = await login(email.trim().toLowerCase(), password);
      // CLINICIAN lands on the portal; everyone else gets the admin
      // /dashboard which the existing admin/eval/compliance pages
      // already route off.
      router.push(auth.role === "CLINICIAN" ? "/portal/dashboard" : "/dashboard");
      router.refresh();
    } catch (err) {
      const msg = err instanceof Error ? err.message : "Sign-in failed";
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
    <div className="relative flex min-h-screen items-center justify-center overflow-hidden aurion-chrome-navy px-4">
      {/* Ambient gold halo — premium hero glow behind the form card. */}
      <div
        aria-hidden
        className="pointer-events-none absolute -top-48 left-1/2 h-[640px] w-[760px] -translate-x-1/2 rounded-full bg-gold-500/[0.10] blur-3xl animate-aurion-glow"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -bottom-40 right-[-10%] h-[440px] w-[440px] rounded-full bg-navy-500/30 blur-3xl"
      />
      <div
        aria-hidden
        className="pointer-events-none absolute -top-20 -left-20 h-[360px] w-[360px] rounded-full bg-navy-500/20 blur-3xl"
      />

      <div className="relative z-10 w-full max-w-[400px] animate-aurion-slide-up">
        {/* Brand lockup — pixel-identical to the iOS splash hero. */}
        <div className="mb-10 flex justify-center">
          <AurionLogoLockup height={220} glow />
        </div>

        {/* Card */}
        <div className="rounded-aurion-xl bg-white/[0.98] p-8 shadow-[0_24px_60px_-12px_rgba(8,18,38,0.50)] ring-1 ring-white/10 backdrop-blur">
          <h2 className="aurion-title-3 mb-1.5">Sign in</h2>
          <p className="aurion-caption mb-6">
            Use your Aurion email and password.
          </p>

          {error && (
            <div
              role="alert"
              className="mb-5 flex items-start gap-2 rounded-aurion-md bg-red-50 px-3.5 py-3 text-[13px] text-red-700 ring-1 ring-inset ring-red-600/15"
            >
              <ExclamationCircleIcon className="mt-0.5 h-4 w-4 shrink-0 text-red-500" />
              <span className="leading-snug">{error}</span>
            </div>
          )}

          <form onSubmit={handleSubmit} className="space-y-4">
            <label className="block">
              <span className="aurion-micro mb-1.5 block">Email</span>
              <input
                type="email"
                value={email}
                onChange={(e) => setEmail(e.target.value)}
                autoComplete="email"
                autoFocus
                required
                disabled={loading}
                placeholder="you@aurionclinical.com"
                className="form-input"
              />
            </label>

            <label className="block">
              <span className="aurion-micro mb-1.5 block">Password</span>
              <div className="relative">
                <input
                  type={showPassword ? "text" : "password"}
                  value={password}
                  onChange={(e) => setPassword(e.target.value)}
                  autoComplete="current-password"
                  required
                  disabled={loading}
                  className="form-input pr-11"
                />
                <button
                  type="button"
                  onClick={() => setShowPassword((v) => !v)}
                  className="absolute inset-y-0 right-0 flex items-center px-3 text-navy-400 hover:text-navy-700 transition-colors duration-short"
                  tabIndex={-1}
                  aria-label={showPassword ? "Hide password" : "Show password"}
                >
                  {showPassword ? (
                    <EyeSlashIcon className="h-4 w-4" />
                  ) : (
                    <EyeIcon className="h-4 w-4" />
                  )}
                </button>
              </div>
            </label>

            <Button
              type="submit"
              variant="primary"
              size="lg"
              loading={loading}
              fullWidth
              className="mt-2"
            >
              Sign in
            </Button>
          </form>

          {IS_LOCAL && (
            <details className="group mt-6 rounded-aurion-md bg-canvas px-3.5 py-3 ring-1 ring-inset ring-hairline">
              <summary className="cursor-pointer text-[12.5px] font-semibold text-navy-700 marker:hidden flex items-center justify-between">
                <span>Local dev credentials</span>
                <span className="text-navy-300 group-open:rotate-180 transition-transform duration-short">
                  ▾
                </span>
              </summary>
              <ul className="mt-3 space-y-1.5 text-[12px] font-mono text-navy-700">
                <DevCredRow role="ADMIN" email="admin@aurionclinical.com" pw="admin" />
                <DevCredRow role="CLINICIAN" email="perry@creoq.ca" pw="perry" />
                <DevCredRow role="CLINICIAN" email="marie@creoq.ca" pw="marie" />
                <DevCredRow role="COMPLIANCE" email="compliance@aurionclinical.com" pw="compliance" />
                <DevCredRow role="EVAL" email="eval@aurionclinical.com" pw="eval" />
              </ul>
              <p className="mt-2.5 text-[11px] text-navy-400">
                Seeded by the backend when <code>APP_ENV=local</code>. Cognito
                hosted UI is paused.
              </p>
            </details>
          )}
        </div>

        <p className="mt-8 flex items-center justify-center gap-1.5 text-center text-[11.5px] text-white/55 tracking-wide">
          <LockClosedIcon className="h-3 w-3" />
          Aurion Clinical AI &middot; For authorized personnel only
        </p>
      </div>
    </div>
  );
}

function DevCredRow({
  role,
  email,
  pw,
}: {
  role: string;
  email: string;
  pw: string;
}) {
  return (
    <li className="flex items-baseline gap-2">
      <span className="inline-flex shrink-0 items-center rounded-aurion-xs bg-navy-50 px-1.5 py-0.5 text-[9.5px] font-bold tracking-wider text-navy-600 uppercase">
        {role}
      </span>
      <span>{email}</span>
      <span className="text-navy-300">/</span>
      <span className="text-navy-500">{pw}</span>
    </li>
  );
}
