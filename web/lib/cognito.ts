/**
 * Cognito hosted-UI OAuth (Authorization Code + PKCE) client for the
 * web portal. Mirrors `ios/Aurion/Aurion/Network/CognitoAuth.swift` —
 * if you change a shape here, glance at the iOS version so the two
 * stay reconcilable for a future eyes-on-both-platforms reader.
 *
 * Token storage:
 *   `sessionStorage` — id_token, access_token, refresh_token, expires_at.
 *   Trade-off vs. httpOnly cookies discussed in the plan
 *   (docs/plans/WEB-COGNITO-UI-cognito-hosted-ui.md). HttpOnly cookies
 *   would require a Next.js middleware / route handler to set them
 *   server-side. Out of scope here.
 *
 * MFA:
 *   `mfa_configuration = "ON"` on the user pool means Cognito's hosted
 *   UI handles the TOTP enrollment + challenge. This module never
 *   touches MFA directly.
 */

const HOSTED_UI_BASE =
  process.env.NEXT_PUBLIC_COGNITO_HOSTED_UI_BASE ??
  "https://aurion-dev.auth.ca-central-1.amazoncognito.com";
const CLIENT_ID =
  process.env.NEXT_PUBLIC_COGNITO_CLIENT_ID ?? "78kr08fp0q4gmgm5qpu65voq5j";
const REDIRECT_URI =
  process.env.NEXT_PUBLIC_COGNITO_REDIRECT_URI ??
  (typeof window !== "undefined"
    ? `${window.location.origin}/api/auth/callback/cognito`
    : "https://portal-dev.aurionclinical.com/api/auth/callback/cognito");
const LOGOUT_URI =
  process.env.NEXT_PUBLIC_COGNITO_LOGOUT_URI ??
  (typeof window !== "undefined"
    ? `${window.location.origin}/auth/signed-out`
    : "https://portal-dev.aurionclinical.com/auth/signed-out");

const STORAGE_ID = "aurion_cognito_id_token";
const STORAGE_ACCESS = "aurion_cognito_access_token";
const STORAGE_REFRESH = "aurion_cognito_refresh_token";
const STORAGE_EXPIRES = "aurion_cognito_expires_at";

const STORAGE_PKCE_VERIFIER = "aurion_cognito_pkce_verifier";
const STORAGE_PKCE_STATE = "aurion_cognito_pkce_state";

/* ─── PKCE helpers ───────────────────────────────────────────────────────── */

function randomBytes(n: number): Uint8Array {
  const buf = new Uint8Array(n);
  crypto.getRandomValues(buf);
  return buf;
}

function base64UrlEncode(bytes: ArrayBuffer | Uint8Array): string {
  const arr = bytes instanceof Uint8Array ? bytes : new Uint8Array(bytes);
  // Avoid `for…of` on Uint8Array — tsconfig target is pre-es2015 by
  // default, which trips "can only be iterated through with
  // downlevelIteration." Index loop sidesteps the flag dance.
  let bin = "";
  for (let i = 0; i < arr.length; i++) {
    bin += String.fromCharCode(arr[i]);
  }
  return btoa(bin).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/g, "");
}

async function sha256(input: string): Promise<ArrayBuffer> {
  return crypto.subtle.digest("SHA-256", new TextEncoder().encode(input));
}

async function makePkcePair(): Promise<{ verifier: string; challenge: string }> {
  const verifier = base64UrlEncode(randomBytes(32)); // 43-char base64url
  const challenge = base64UrlEncode(await sha256(verifier));
  return { verifier, challenge };
}

/* ─── Public API ─────────────────────────────────────────────────────────── */

/**
 * Kicks off the OAuth flow: stashes PKCE + state in sessionStorage,
 * then redirects to Cognito's hosted UI. Returns a Promise so callers
 * can `await` for tests; in the browser the redirect happens before
 * the promise resolves.
 */
export async function startSignIn(): Promise<void> {
  const { verifier, challenge } = await makePkcePair();
  const state = base64UrlEncode(randomBytes(16));

  sessionStorage.setItem(STORAGE_PKCE_VERIFIER, verifier);
  sessionStorage.setItem(STORAGE_PKCE_STATE, state);

  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    response_type: "code",
    scope: "openid email profile aws.cognito.signin.user.admin",
    redirect_uri: REDIRECT_URI,
    code_challenge: challenge,
    code_challenge_method: "S256",
    state,
  });
  window.location.href = `${HOSTED_UI_BASE}/oauth2/authorize?${params}`;
}

interface TokenResponse {
  id_token: string;
  access_token: string;
  refresh_token?: string;
  expires_in: number;
  token_type: string;
}

/**
 * Exchanges an authorization code (returned to the callback page) for
 * a token bundle. Stores the bundle in sessionStorage and returns it.
 *
 * Throws if the state parameter doesn't match what we stashed at
 * startSignIn — defends against CSRF on the redirect URI.
 */
export async function exchangeCodeForTokens(
  code: string,
  returnedState: string,
): Promise<TokenResponse> {
  const expectedState = sessionStorage.getItem(STORAGE_PKCE_STATE);
  if (!expectedState || expectedState !== returnedState) {
    throw new Error("OAuth state mismatch — possible CSRF attempt");
  }
  const verifier = sessionStorage.getItem(STORAGE_PKCE_VERIFIER);
  if (!verifier) {
    throw new Error("Missing PKCE verifier — restart the sign-in flow");
  }

  const body = new URLSearchParams({
    grant_type: "authorization_code",
    client_id: CLIENT_ID,
    code,
    redirect_uri: REDIRECT_URI,
    code_verifier: verifier,
  });

  const res = await fetch(`${HOSTED_UI_BASE}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    const text = await res.text();
    throw new Error(`Token exchange failed: ${res.status} ${text}`);
  }
  const tokens = (await res.json()) as TokenResponse;
  storeTokens(tokens);

  // PKCE values are single-use.
  sessionStorage.removeItem(STORAGE_PKCE_VERIFIER);
  sessionStorage.removeItem(STORAGE_PKCE_STATE);
  return tokens;
}

/**
 * Exchanges the stored refresh_token for a fresh id_token /
 * access_token. Returns null if no refresh_token is stored or the
 * exchange fails — caller should redirect to /login in that case.
 */
export async function refreshTokens(): Promise<TokenResponse | null> {
  const refresh = sessionStorage.getItem(STORAGE_REFRESH);
  if (!refresh) return null;

  const body = new URLSearchParams({
    grant_type: "refresh_token",
    client_id: CLIENT_ID,
    refresh_token: refresh,
  });

  const res = await fetch(`${HOSTED_UI_BASE}/oauth2/token`, {
    method: "POST",
    headers: { "Content-Type": "application/x-www-form-urlencoded" },
    body,
  });
  if (!res.ok) {
    clearStoredTokens();
    return null;
  }
  // Cognito's refresh response omits refresh_token (the original keeps
  // ticking until 30d). Preserve it manually.
  const tokens = (await res.json()) as TokenResponse;
  tokens.refresh_token = tokens.refresh_token ?? refresh;
  storeTokens(tokens);
  return tokens;
}

/**
 * Clears all stored tokens and redirects to Cognito's /logout
 * endpoint so the hosted UI session terminates too. After Cognito
 * processes the logout, it redirects back to LOGOUT_URI.
 */
export function signOut(): void {
  clearStoredTokens();
  const params = new URLSearchParams({
    client_id: CLIENT_ID,
    logout_uri: LOGOUT_URI,
  });
  window.location.href = `${HOSTED_UI_BASE}/logout?${params}`;
}

/* ─── Storage helpers ────────────────────────────────────────────────────── */

function storeTokens(tokens: TokenResponse): void {
  sessionStorage.setItem(STORAGE_ID, tokens.id_token);
  sessionStorage.setItem(STORAGE_ACCESS, tokens.access_token);
  if (tokens.refresh_token) {
    sessionStorage.setItem(STORAGE_REFRESH, tokens.refresh_token);
  }
  const expiresAt = Date.now() + tokens.expires_in * 1000;
  sessionStorage.setItem(STORAGE_EXPIRES, String(expiresAt));
}

function clearStoredTokens(): void {
  sessionStorage.removeItem(STORAGE_ID);
  sessionStorage.removeItem(STORAGE_ACCESS);
  sessionStorage.removeItem(STORAGE_REFRESH);
  sessionStorage.removeItem(STORAGE_EXPIRES);
}

export function getStoredIdToken(): string | null {
  if (typeof sessionStorage === "undefined") return null;
  return sessionStorage.getItem(STORAGE_ID);
}

export function getStoredRefreshToken(): string | null {
  if (typeof sessionStorage === "undefined") return null;
  return sessionStorage.getItem(STORAGE_REFRESH);
}

/**
 * True when the stored id_token is past its expiry timestamp.
 * Callers should refresh before making an authenticated request.
 */
export function tokenIsStale(): boolean {
  if (typeof sessionStorage === "undefined") return false;
  const raw = sessionStorage.getItem(STORAGE_EXPIRES);
  if (!raw) return true;
  const at = Number(raw);
  if (!Number.isFinite(at)) return true;
  // 30s skew to avoid a token that expires mid-request.
  return Date.now() >= at - 30_000;
}
