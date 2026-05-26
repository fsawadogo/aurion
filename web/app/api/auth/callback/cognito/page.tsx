"use client";

import { useEffect, useState } from "react";
import { useRouter, useSearchParams } from "next/navigation";
import { exchangeCodeForTokens } from "@/lib/cognito";

export default function CognitoCallbackPage() {
  const router = useRouter();
  const params = useSearchParams();
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    const code = params.get("code");
    const state = params.get("state");
    const cognitoError = params.get("error");
    const cognitoErrorDescription = params.get("error_description");

    if (cognitoError) {
      setError(cognitoErrorDescription || cognitoError);
      return;
    }
    if (!code || !state) {
      setError("Missing authorization code or state in callback URL.");
      return;
    }

    exchangeCodeForTokens(code, state)
      .then(() => {
        // Replace so the back button doesn't bounce them to the
        // callback URL with a now-consumed code.
        router.replace("/dashboard");
      })
      .catch((err: unknown) => {
        setError(
          err instanceof Error ? err.message : "Token exchange failed",
        );
      });
  }, [params, router]);

  return (
    <div className="relative flex min-h-screen items-center justify-center bg-navy px-4">
      <div className="rounded-2xl bg-white p-8 text-center shadow-2xl ring-1 ring-white/10">
        {error ? (
          <>
            <h1 className="mb-3 text-lg font-semibold text-red-700">
              Sign-in failed
            </h1>
            <p className="mb-4 text-sm text-gray-600">{error}</p>
            <button
              onClick={() => router.push("/login")}
              className="text-sm font-medium text-gold-600 underline hover:text-gold-700"
            >
              Try again
            </button>
          </>
        ) : (
          <>
            <h1 className="mb-2 text-lg font-semibold text-navy-700">
              Signing you in…
            </h1>
            <p className="text-sm text-gray-500">
              Exchanging the authorization code for tokens.
            </p>
          </>
        )}
      </div>
    </div>
  );
}
