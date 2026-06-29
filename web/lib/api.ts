import type {
  AuditEvent,
  AuditFilters,
  AuthResponse,
  CapturedMediaList,
  ConfigChangeEvent,
  CreateUserPayload,
  CurrentUser,
  EvalAssignee,
  EvalScoreSubmission,
  EvalSession,
  EvalSessionDetail,
  FeatureFlags,
  LoginResult,
  MaskingReport,
  MediaDownloadUrls,
  MetricFilters,
  MetricTimeseriesFilters,
  MetricTimeseriesResponse,
  PaginatedResponse,
  PilotMetric,
  ProviderConfig,
  ProvidersOverview,
  ProviderType,
  AdminTemplateDetail,
  AlertListResponse,
  ComplianceReportListResponse,
  ComplianceReportMetadata,
  ComplianceReportType,
  ProviderCompareResponse,
  ProviderQualityCompareResponse,
  AdminTemplateListResponse,
  AdoptionResponse,
  CustomTemplate,
  OperationalAlert,
  ProviderUsageResponse,
  Session,
  TemplateDefinition,
  SessionDetail,
  SessionFilters,
  UpdateFeatureFlagsResponse,
  UpdateUserPayload,
  User,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* ─── Token storage (backend bcrypt-JWT — no Cognito) ─────────────────────────
 *
 * Access + refresh tokens live in non-httpOnly cookies so the client JS can
 * attach the bearer header and run the silent-refresh-on-401 flow. This
 * matches the portal's pre-existing `aurion_token` cookie approach. The XSS
 * exposure of a readable token is an accepted MVP trade-off for an internal
 * admin portal; post-MVP hardening = httpOnly cookies + a server-side refresh
 * proxy. See docs/plans/auth-pivot-web.md.
 */
const ACCESS_COOKIE = "aurion_token";
const REFRESH_COOKIE = "aurion_refresh";
const ACCESS_MAX_AGE = 86_400; // 24h cookie; the JWT itself expires sooner and refresh covers the gap
const REFRESH_MAX_AGE = 2_592_000; // 30d

function readCookie(name: string): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(
    new RegExp(`(?:^|;\\s*)${name}=([^;]*)`),
  );
  return match ? decodeURIComponent(match[1]) : null;
}

function writeCookie(name: string, value: string, maxAge: number): void {
  if (typeof document === "undefined") return;
  // `Secure` whenever the page is served over https (i.e. all deployed
  // environments) so the bearer + 30-day refresh token are never attached
  // to a plaintext-HTTP request. Omitted on http://localhost so local dev
  // still works (localhost is a secure context, but be explicit).
  const secure =
    typeof window !== "undefined" && window.location.protocol === "https:"
      ? "; Secure"
      : "";
  document.cookie = `${name}=${encodeURIComponent(value)}; path=/; SameSite=Strict${secure}; max-age=${maxAge}`;
}

function deleteCookie(name: string): void {
  if (typeof document === "undefined") return;
  document.cookie = `${name}=; path=/; max-age=0`;
}

/** Persist the tokens from a successful login / refresh / MFA-verify. */
function storeTokens(data: AuthResponse): void {
  writeCookie(ACCESS_COOKIE, data.access_token, ACCESS_MAX_AGE);
  writeCookie(REFRESH_COOKIE, data.refresh_token, REFRESH_MAX_AGE);
}

/** Clear all auth state (logout, or a refresh that failed). */
function clearTokens(): void {
  deleteCookie(ACCESS_COOKIE);
  deleteCookie(REFRESH_COOKIE);
}

/** Outcome of a refresh attempt:
 *   "ok"     — new token pair stored, retry the request.
 *   "failed" — server rejected the refresh (revoked/expired); tokens
 *              cleared, the caller should bounce to /login.
 *   "error"  — couldn't even reach the server (network blip); tokens kept,
 *              the caller should surface a transient error, NOT log out. */
type RefreshOutcome = "ok" | "failed" | "error";

// Single-flight guard. The backend ROTATES the refresh token on every
// /refresh (the presented token is revoked, a new pair issued). Without
// this, the dashboard's parallel requests all 401 when the ~30m access
// token expires, all read the same refresh cookie, and race to redeem it
// — only one wins; the losers present an already-rotated token, fail, and
// spuriously bounce the user to /login. Caching the in-flight promise makes
// concurrent callers share one rotation and all see the same new pair.
let refreshInFlight: Promise<RefreshOutcome> | null = null;

async function doRefresh(): Promise<RefreshOutcome> {
  const refresh_token = readCookie(REFRESH_COOKIE);
  if (!refresh_token) return "failed";
  try {
    const res = await fetch(`${API_BASE}/api/v1/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token }),
    });
    if (!res.ok) {
      clearTokens();
      return "failed";
    }
    storeTokens((await res.json()) as AuthResponse);
    return "ok";
  } catch {
    return "error"; // network blip — keep tokens, let a later request retry
  }
}

/** Exchange the stored refresh token for a fresh access+refresh pair,
 * de-duplicating concurrent callers so the rotating token is redeemed once. */
function refreshAccessToken(): Promise<RefreshOutcome> {
  if (!refreshInFlight) {
    refreshInFlight = doRefresh().finally(() => {
      refreshInFlight = null;
    });
  }
  return refreshInFlight;
}

/* ─── Helpers ────────────────────────────────────────────────────────────── */

/** Resolve the bearer token for outgoing API requests — the backend
 * bcrypt-JWT access token from the `aurion_token` cookie. Returns null
 * if absent; the caller's request then fails 401 and fetchWithAuth
 * routes to /login. */
function getToken(): string | null {
  return readCookie(ACCESS_COOKIE);
}

function buildQuery<T extends object>(params: T): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value !== undefined && value !== null && value !== "") {
      parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
    }
  }
  return parts.length > 0 ? `?${parts.join("&")}` : "";
}

/** Error thrown by `fetchWithAuth` for any non-OK response. Carries the HTTP
 * status + raw body so callers can branch (role-403 vs 404 vs 5xx) and
 * `humanizeError` can produce friendly copy. `.message` stays the legacy
 * `API <status>: <body>` string for backward compatibility. */
export class ApiError extends Error {
  readonly status: number;
  readonly body: string;
  constructor(status: number, body: string) {
    super(`API ${status}: ${body}`);
    this.name = "ApiError";
    this.status = status;
    this.body = body;
  }
}

function extractDetail(body: string): string | null {
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (typeof parsed?.detail === "string") return parsed.detail;
    // FastAPI validation errors: detail is an array of { msg, ... }.
    const first = Array.isArray(parsed?.detail) ? parsed.detail[0] : null;
    if (first && typeof (first as { msg?: unknown }).msg === "string") {
      return (first as { msg: string }).msg;
    }
  } catch {
    /* body wasn't JSON */
  }
  return null;
}

/** Turn a thrown API/network error into a short, human-friendly banner
 * message — never the raw `API 403: {"detail":...}` JSON. Use in catch
 * blocks instead of `e.message`. Pass a context-specific `fallback` for the
 * unclassifiable case. */
export function humanizeError(
  e: unknown,
  fallback = "Something went wrong.",
): string {
  if (e instanceof ApiError) {
    if (e.status === 403) {
      return /CLINICIAN role only/i.test(e.body)
        ? "This section is only available to clinician accounts."
        : "You don't have permission to view this.";
    }
    if (e.status === 404) return "Not found.";
    if (e.status === 429) return "Too many requests — please wait a moment.";
    if (e.status >= 500) {
      return "Something went wrong on our end. Please try again.";
    }
    return extractDetail(e.body) ?? fallback;
  }
  if (e instanceof Error) {
    if (/Failed to fetch|NetworkError|Load failed/i.test(e.message)) {
      return "Couldn't reach Aurion. Check your connection and try again.";
    }
    return e.message || fallback;
  }
  return fallback;
}

/** Pull a prompt-validator 400 detail (`{ message, matched_phrase }`) into a
 * friendly line — the Prompt Studio author/publish endpoints and the
 * per-physician prompt-save endpoints share this shape. Falls back to
 * `humanizeError` for any other error. */
export function parseDetailError(e: unknown, fallback: string): string {
  if (e instanceof ApiError) {
    try {
      const detail = (JSON.parse(e.body) as { detail?: unknown }).detail;
      if (detail && typeof detail === "object") {
        const d = detail as { message?: string; matched_phrase?: string | null };
        if (d.matched_phrase) return `${d.message ?? fallback} (“${d.matched_phrase}”)`;
        if (d.message) return d.message;
      }
    } catch {
      /* non-JSON body — fall through */
    }
  }
  return humanizeError(e, fallback);
}

export async function fetchWithAuth(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  const buildHeaders = (): Record<string, string> => {
    const token = getToken();
    const h: Record<string, string> = {
      "Content-Type": "application/json",
      ...(options.headers as Record<string, string> | undefined),
    };
    if (token) h["Authorization"] = `Bearer ${token}`;
    return h;
  };

  let response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers: buildHeaders(),
  });

  // One silent refresh + retry on 401 — if the rotated refresh works the
  // user never sees the redirect. Concurrent 401s share one refresh via the
  // single-flight guard, so the rotating token is redeemed exactly once.
  if (response.status === 401 && typeof window !== "undefined") {
    const outcome = await refreshAccessToken();
    if (outcome === "ok") {
      response = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: buildHeaders(),
      });
    }
    // Bounce only on a definitive failure (server rejected the refresh, or
    // the retry is still 401). A transient network error ("error") keeps the
    // session intact — the caller just sees this 401 and can retry later.
    if (response.status === 401 && outcome !== "error") {
      clearTokens();
      window.location.href = "/login";
    }
  }

  if (!response.ok) {
    const body = await response.text();
    throw new ApiError(response.status, body);
  }
  return response;
}

/* ─── Auth ───────────────────────────────────────────────────────────────── */

/** Pull the FastAPI `{ detail }` string out of an error body so callers
 * can match on clean copy (e.g. the 429 lockout line) rather than raw JSON.
 * Falls back to the raw text for non-JSON bodies. */
async function loginErrorDetail(res: Response): Promise<string> {
  const body = await res.text();
  try {
    const parsed = JSON.parse(body) as { detail?: unknown };
    if (parsed && typeof parsed.detail === "string") return parsed.detail;
  } catch {
    /* non-JSON body — keep the raw text */
  }
  return body;
}

/** Sign in against the backend bcrypt-JWT API.
 *
 * Returns either a full {@link AuthResponse} (tokens stored, ready to
 * route) or an {@link MfaRequiredResponse} the caller must finish via
 * {@link verifyMfaLogin}. The MFA branch deliberately does NOT store
 * tokens — there are none until the challenge is satisfied. */
export async function login(
  email: string,
  password: string,
): Promise<LoginResult> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    throw new Error(`Login failed: ${await loginErrorDetail(res)}`);
  }
  const data = (await res.json()) as LoginResult;
  if ("mfa_required" in data) return data; // caller prompts for the TOTP code
  storeTokens(data);
  return data;
}

/** Finish an MFA-gated login with the 6-digit TOTP code. */
export async function verifyMfaLogin(
  mfa_challenge_token: string,
  code: string,
): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/mfa/verify-login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ mfa_challenge_token, code }),
  });
  if (!res.ok) {
    throw new Error(`Login failed: ${await loginErrorDetail(res)}`);
  }
  const data = (await res.json()) as AuthResponse;
  storeTokens(data);
  return data;
}

/** Sign out: best-effort revoke the refresh token server-side, clear the
 * local cookies, and bounce to /login. */
export function logout(): void {
  const refresh_token = readCookie(REFRESH_COOKIE);
  if (refresh_token) {
    // Fire-and-forget — we clear locally regardless of the result.
    void fetch(`${API_BASE}/api/v1/auth/logout`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token }),
      keepalive: true,
    }).catch(() => {});
  }
  clearTokens();
  if (typeof window !== "undefined") {
    window.location.href = "/login";
  }
}

export async function getMe(): Promise<CurrentUser> {
  const res = await fetchWithAuth("/api/v1/auth/me");
  return res.json();
}

/** Kick off a password reset by emailing the user a link.
 *
 * The backend ALWAYS returns 204 regardless of whether the email
 * matches an account (account-existence-neutral by design). Callers
 * therefore should not branch on the response; just show the same
 * "if that email is on file…" confirmation either way.
 *
 * No `fetchWithAuth` — this endpoint is public (no Bearer token).
 *
 * Throws only on transport-level errors (network down, CORS, 5xx).
 * 4xx from the backend is exceptional for this route — schema
 * validation only — and the page surfaces a generic "couldn't reach
 * Aurion" without leaking detail.
 */
export async function requestPasswordReset(email: string): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/forgot-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email }),
  });
  if (!res.ok) {
    // 422 (bad email shape) leaks no account info — surface the
    // generic transport error and let the caller show the
    // existence-neutral confirmation anyway.
    throw new Error(`Forgot-password request failed: ${res.status}`);
  }
}

/** Consume a reset token + set the new password.
 *
 * Returns void on 204. Throws an Error whose `.message` carries the
 * backend's `detail` field on 4xx — pages surface this verbatim to
 * the user (the backend already crafts user-safe messages:
 * "Invalid or expired reset token.").
 *
 * The raw token never reaches console, analytics, or logs from this
 * helper — it goes straight from the function arg into the POST
 * body, then the reference is dropped.
 */
export async function resetPassword(
  token: string,
  newPassword: string,
): Promise<void> {
  const res = await fetch(`${API_BASE}/api/v1/auth/reset-password`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ token, new_password: newPassword }),
  });
  if (res.status === 204) return;
  if (!res.ok) {
    // Backend wraps errors as { detail: "..." }. Surface the detail
    // when present so users see "Invalid or expired reset token."
    // instead of a generic API code.
    let detail = `Reset failed (${res.status})`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      // ignore — body wasn't JSON, use the generic message
    }
    throw new Error(detail);
  }
}

/* ─── Users ──────────────────────────────────────────────────────────────── */

export async function getUsers(): Promise<User[]> {
  const res = await fetchWithAuth("/api/v1/admin/users");
  return res.json();
}

export async function createUser(payload: CreateUserPayload): Promise<User> {
  const res = await fetchWithAuth("/api/v1/admin/users", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function updateUser(
  userId: string,
  payload: UpdateUserPayload,
): Promise<User> {
  const res = await fetchWithAuth(`/api/v1/admin/users/${userId}`, {
    method: "PATCH",
    body: JSON.stringify(payload),
  });
  return res.json();
}

export async function deactivateUser(userId: string): Promise<void> {
  await fetchWithAuth(`/api/v1/admin/users/${userId}/deactivate`, {
    method: "POST",
  });
}

/* ─── Audit Log ──────────────────────────────────────────────────────────── */

export async function getAuditLog(
  filters: AuditFilters = {},
): Promise<PaginatedResponse<AuditEvent>> {
  const res = await fetchWithAuth(`/api/v1/admin/audit${buildQuery(filters)}`);
  return res.json();
}

export async function getSessionAudit(
  sessionId: string,
): Promise<AuditEvent[]> {
  const res = await fetchWithAuth(
    `/api/v1/admin/audit/session/${encodeURIComponent(sessionId)}`,
  );
  return res.json();
}

export async function exportAuditCsv(
  filters: AuditFilters = {},
): Promise<Blob> {
  const res = await fetchWithAuth(
    `/api/v1/admin/audit/export${buildQuery(filters)}`,
  );
  return res.blob();
}

/* ─── PHI Masking Report ─────────────────────────────────────────────────── */

export async function getMaskingReport(
  filters: { date_from?: string; date_to?: string; clinician_id?: string } = {},
): Promise<MaskingReport> {
  const res = await fetchWithAuth(
    `/api/v1/admin/masking/report${buildQuery(filters)}`,
  );
  return res.json();
}

/* ─── Provider Config ────────────────────────────────────────────────────── */

export async function getConfig(): Promise<ProviderConfig> {
  const res = await fetchWithAuth("/api/v1/admin/config/current");
  return res.json();
}

export async function getConfigHistory(): Promise<ConfigChangeEvent[]> {
  const res = await fetchWithAuth("/api/v1/admin/config/history");
  return res.json();
}

/* ─── Feature Flags ──────────────────────────────────────────────────────── */
//
// ADMIN-only writer surface that backs the /portal/admin/feature-flags
// page. GET returns the live AppConfig feature_flags block; POST pushes
// a new AppConfig hosted-version and starts a deployment. See
// backend/app/api/v1/admin/feature_flags.py — both helpers go through
// the standard fetchWithAuth path so the bearer token + 401 retry
// machinery applies.

export async function getFeatureFlags(): Promise<FeatureFlags> {
  const res = await fetchWithAuth("/api/v1/admin/feature-flags");
  return res.json();
}

export async function updateFeatureFlags(
  payload: FeatureFlags,
): Promise<UpdateFeatureFlagsResponse> {
  const res = await fetchWithAuth("/api/v1/admin/feature-flags", {
    method: "POST",
    body: JSON.stringify(payload),
  });
  return res.json();
}

/* ─── Runtime AI-provider overrides (admin / compliance) ─────────────────────
 *
 * GET shows per-type AppConfig baseline + active override + effective value.
 * PUT pins a runtime override (immediate, audited); DELETE clears it so the
 * type falls back to its AppConfig baseline. ADMIN or COMPLIANCE_OFFICER.
 */
export async function getProviders(): Promise<ProvidersOverview> {
  const res = await fetchWithAuth("/api/v1/admin/providers");
  return res.json();
}

export async function setProviderOverride(
  providerType: ProviderType,
  value: string,
  reason?: string,
): Promise<ProvidersOverview> {
  const res = await fetchWithAuth(`/api/v1/admin/providers/${providerType}`, {
    method: "PUT",
    body: JSON.stringify({ value, reason }),
  });
  return res.json();
}

export async function clearProviderOverride(
  providerType: ProviderType,
): Promise<ProvidersOverview> {
  const res = await fetchWithAuth(`/api/v1/admin/providers/${providerType}`, {
    method: "DELETE",
  });
  return res.json();
}

/**
 * Aggregated provider call telemetry over a window (#73). All params
 * optional: omitted bounds mean "all recorded usage"; omitted type means
 * all three pipeline stages. ADMIN + COMPLIANCE_OFFICER.
 */
/* ─── Compliance reports (admin, #77) ────────────────────────────────────── */

export async function listComplianceReports(opts?: {
  reportType?: ComplianceReportType;
  limit?: number;
  offset?: number;
}): Promise<ComplianceReportListResponse> {
  const params = new URLSearchParams();
  if (opts?.reportType) params.set("report_type", opts.reportType);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  const qs = params.toString();
  const res = await fetchWithAuth(
    `/api/v1/admin/compliance/reports${qs ? `?${qs}` : ""}`,
  );
  return res.json();
}

/** Generate a new signed snapshot. Omitted bounds = full history. */
export async function generateComplianceReport(
  reportType: ComplianceReportType,
  opts?: { since?: string; until?: string },
): Promise<ComplianceReportMetadata> {
  const res = await fetchWithAuth("/api/v1/admin/compliance/reports", {
    method: "POST",
    body: JSON.stringify({
      report_type: reportType,
      since: opts?.since ?? null,
      until: opts?.until ?? null,
    }),
  });
  return res.json();
}

/** Download the persisted CSV bytes (sha256 echoed in X-Aurion-Sha256). */
export async function downloadComplianceReport(id: string): Promise<Blob> {
  const res = await fetchWithAuth(
    `/api/v1/admin/compliance/reports/${id}/download`,
  );
  return res.blob();
}

/* ─── Operational alerts (admin, #76) ────────────────────────────────────── */

export async function listAlerts(opts?: {
  status?: "open" | "acknowledged";
  severity?: "info" | "warning" | "critical";
  limit?: number;
  offset?: number;
}): Promise<AlertListResponse> {
  const params = new URLSearchParams();
  if (opts?.status) params.set("status", opts.status);
  if (opts?.severity) params.set("severity", opts.severity);
  if (opts?.limit !== undefined) params.set("limit", String(opts.limit));
  if (opts?.offset !== undefined) params.set("offset", String(opts.offset));
  const qs = params.toString();
  const res = await fetchWithAuth(`/api/v1/admin/alerts${qs ? `?${qs}` : ""}`);
  return res.json();
}

/** Idempotent — re-acknowledging preserves the first acknowledger. */
export async function acknowledgeAlert(id: string): Promise<OperationalAlert> {
  const res = await fetchWithAuth(`/api/v1/admin/alerts/${id}/acknowledge`, {
    method: "PATCH",
  });
  return res.json();
}

/* ─── Built-in template management (admin, #72) ──────────────────────────── */

export async function getAdminTemplates(): Promise<AdminTemplateListResponse> {
  const res = await fetchWithAuth("/api/v1/admin/templates");
  return res.json();
}

export async function getAdminTemplateDetail(
  key: string,
): Promise<AdminTemplateDetail> {
  const res = await fetchWithAuth(`/api/v1/admin/templates/${key}`);
  return res.json();
}

/** Save an admin override for a bundled template (live at runtime). */
export async function putAdminTemplate(
  key: string,
  template: TemplateDefinition,
): Promise<AdminTemplateDetail> {
  const res = await fetchWithAuth(`/api/v1/admin/templates/${key}`, {
    method: "PUT",
    body: JSON.stringify(template),
  });
  return res.json();
}

/** Delete the override — the template reverts to its disk default. */
export async function revertAdminTemplate(key: string): Promise<void> {
  await fetchWithAuth(`/api/v1/admin/templates/${key}`, { method: "DELETE" });
}

/* ─── Shared / org templates (admin, tpl-04) ─────────────────────────────────
 * Admin authors a custom template marked shared; it surfaces read-only in every
 * clinician's library + the upload/visit picker (via list_for_owner). Returns
 * the same CustomTemplate shape the clinician /me endpoints use. */

export async function listSharedTemplates(): Promise<CustomTemplate[]> {
  const res = await fetchWithAuth("/api/v1/admin/shared-templates");
  return res.json();
}

export async function createSharedTemplate(
  template: TemplateDefinition,
): Promise<CustomTemplate> {
  const res = await fetchWithAuth("/api/v1/admin/shared-templates", {
    method: "POST",
    body: JSON.stringify({ template }),
  });
  return res.json();
}

export async function updateSharedTemplate(
  id: string,
  template: TemplateDefinition,
): Promise<CustomTemplate> {
  const res = await fetchWithAuth(`/api/v1/admin/shared-templates/${id}`, {
    method: "PUT",
    body: JSON.stringify({ template }),
  });
  return res.json();
}

export async function deleteSharedTemplate(id: string): Promise<void> {
  await fetchWithAuth(`/api/v1/admin/shared-templates/${id}`, {
    method: "DELETE",
  });
}

/**
 * Adoption & ROI rollup (#71). EVAL_TEAM + ADMIN. `baselineMinutesPerNote`
 * opts time-saved in (echoed back by the backend); omitted → null.
 */
export async function getAdoptionAnalytics(opts?: {
  since?: string;
  until?: string;
  baselineMinutesPerNote?: number;
}): Promise<AdoptionResponse> {
  const params = new URLSearchParams();
  if (opts?.since) params.set("since", opts.since);
  if (opts?.until) params.set("until", opts.until);
  if (opts?.baselineMinutesPerNote !== undefined) {
    params.set("baseline_minutes_per_note", String(opts.baselineMinutesPerNote));
  }
  const qs = params.toString();
  const res = await fetchWithAuth(
    `/api/v1/admin/analytics/adoption${qs ? `?${qs}` : ""}`,
  );
  return res.json();
}

/** Same rollup as CSV (per-clinician rows + TOTAL footer). */
export async function exportAdoptionCsv(opts?: {
  since?: string;
  until?: string;
  baselineMinutesPerNote?: number;
}): Promise<Blob> {
  const params = new URLSearchParams({ format: "csv" });
  if (opts?.since) params.set("since", opts.since);
  if (opts?.until) params.set("until", opts.until);
  if (opts?.baselineMinutesPerNote !== undefined) {
    params.set("baseline_minutes_per_note", String(opts.baselineMinutesPerNote));
  }
  const res = await fetchWithAuth(
    `/api/v1/admin/analytics/adoption?${params.toString()}`,
  );
  return res.blob();
}

/** Operational A-B compare over the usage telemetry (#73/#74). */
export async function compareProviders(opts: {
  a: string;
  b: string;
  providerType: ProviderType;
  since?: string;
  until?: string;
}): Promise<ProviderCompareResponse> {
  const params = new URLSearchParams({
    a: opts.a,
    b: opts.b,
    provider_type: opts.providerType,
  });
  if (opts.since) params.set("since", opts.since);
  if (opts.until) params.set("until", opts.until);
  const res = await fetchWithAuth(
    `/api/v1/admin/providers/compare?${params.toString()}`,
  );
  return res.json();
}

/** Quality A-B compare from eval scores (#74). EVAL_TEAM + ADMIN. */
export async function compareProviderQuality(opts?: {
  since?: string;
  until?: string;
}): Promise<ProviderQualityCompareResponse> {
  const params = new URLSearchParams();
  if (opts?.since) params.set("since", opts.since);
  if (opts?.until) params.set("until", opts.until);
  const qs = params.toString();
  const res = await fetchWithAuth(
    `/api/v1/admin/providers/compare-quality${qs ? `?${qs}` : ""}`,
  );
  return res.json();
}

export async function getProviderUsage(opts?: {
  since?: string;
  until?: string;
  providerType?: ProviderType;
}): Promise<ProviderUsageResponse> {
  const params = new URLSearchParams();
  if (opts?.since) params.set("since", opts.since);
  if (opts?.until) params.set("until", opts.until);
  if (opts?.providerType) params.set("provider_type", opts.providerType);
  const qs = params.toString();
  const res = await fetchWithAuth(`/api/v1/admin/providers/usage${qs ? `?${qs}` : ""}`);
  return res.json();
}

/* ─── Captured Media (admin, #338) ───────────────────────────────────────── */
//
// Windowed media-retention review surface. GET /admin/media lists sessions
// whose raw media is still inside the retention window (ADMIN/EVAL_TEAM/
// COMPLIANCE_OFFICER); GET /admin/media/{id}/download-urls mints presigned
// download URLs (ADMIN/EVAL_TEAM only — compliance is view-only). Both are
// gated behind media_review_retention_enabled: when the flag is off the
// backend returns 403, which the page surfaces as a "not enabled" state.
// See backend/app/api/v1/admin/media.py.

export async function getCapturedMedia(
  params: { page?: number; page_size?: number } = {},
): Promise<CapturedMediaList> {
  const res = await fetchWithAuth(`/api/v1/admin/media${buildQuery(params)}`);
  return res.json();
}

export async function getMediaDownloadUrls(
  sessionId: string,
): Promise<MediaDownloadUrls> {
  const res = await fetchWithAuth(
    `/api/v1/admin/media/${encodeURIComponent(sessionId)}/download-urls`,
  );
  return res.json();
}

/** Permanently delete ANY clinician's session + its media. ADMIN only
 * (backend require_role(ADMIN); 403 for other roles). Append-only audit
 * (`admin_session_deleted`) is preserved. Used by the Captured Media admin
 * delete action. 204 No Content on success. */
export async function adminDeleteSession(sessionId: string): Promise<void> {
  await fetchWithAuth(
    `/api/v1/admin/sessions/${encodeURIComponent(sessionId)}`,
    { method: "DELETE" },
  );
}

/* ─── Pilot Metrics ──────────────────────────────────────────────────────── */

export async function getMetrics(
  filters: MetricFilters = {},
): Promise<PaginatedResponse<PilotMetric>> {
  const res = await fetchWithAuth(
    `/api/v1/admin/metrics${buildQuery(filters)}`,
  );
  return res.json();
}

export async function getMetricsTimeseries(
  filters: MetricTimeseriesFilters = {},
): Promise<MetricTimeseriesResponse> {
  const res = await fetchWithAuth(
    `/api/v1/admin/metrics/timeseries${buildQuery(filters)}`,
  );
  return res.json();
}

/* ─── Sessions ───────────────────────────────────────────────────────────── */

export async function getSessions(
  filters: SessionFilters = {},
): Promise<PaginatedResponse<Session>> {
  const res = await fetchWithAuth(
    `/api/v1/admin/sessions${buildQuery(filters)}`,
  );
  return res.json();
}

export async function getSessionDetail(
  sessionId: string,
): Promise<SessionDetail> {
  const res = await fetchWithAuth(`/api/v1/admin/sessions/${sessionId}`);
  return res.json();
}

/* ─── Eval ───────────────────────────────────────────────────────────────── */

export async function getEvalSessions(): Promise<EvalSession[]> {
  const res = await fetchWithAuth("/api/v1/admin/eval/sessions");
  return res.json();
}

export async function getEvalSession(id: string): Promise<EvalSessionDetail> {
  const res = await fetchWithAuth(`/api/v1/admin/eval/sessions/${id}`);
  return res.json();
}

export async function submitEvalScore(
  id: string,
  scores: EvalScoreSubmission,
): Promise<EvalSession> {
  const res = await fetchWithAuth(`/api/v1/admin/eval/sessions/${id}/score`, {
    method: "POST",
    body: JSON.stringify(scores),
  });
  return res.json();
}

export async function assignEvalSession(
  sessionId: string,
  assigneeEmail: string,
): Promise<EvalSession> {
  const res = await fetchWithAuth(
    `/api/v1/admin/eval/sessions/${sessionId}/assign`,
    {
      method: "POST",
      body: JSON.stringify({ assignee_email: assigneeEmail }),
    },
  );
  return res.json();
}

export async function unassignEvalSession(
  sessionId: string,
): Promise<EvalSession> {
  const res = await fetchWithAuth(
    `/api/v1/admin/eval/sessions/${sessionId}/assign`,
    { method: "DELETE" },
  );
  return res.json();
}

export async function getEvalAssignees(): Promise<EvalAssignee[]> {
  const res = await fetchWithAuth("/api/v1/admin/eval/assignees");
  return res.json();
}

// ── Admin / eval video import (VID-10) ────────────────────────────────────
// ADMIN + EVAL_TEAM surface mirroring the clinician /me/video-imports calls,
// against /api/v1/admin/video-imports. Same request/response shapes; the
// backend attributes the session (on_behalf_of) + auto-advances Stage 2.
import type {
  VideoImportCreateBody,
  VideoImportCreated,
  VideoImportStatus,
} from "@/lib/portal-api";

export async function createAdminVideoImport(
  body: VideoImportCreateBody,
): Promise<VideoImportCreated> {
  const res = await fetchWithAuth("/api/v1/admin/video-imports", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function processAdminVideoImport(
  sessionId: string,
): Promise<VideoImportStatus> {
  const res = await fetchWithAuth(
    `/api/v1/admin/video-imports/${sessionId}/process`,
    { method: "POST" },
  );
  return res.json();
}

export async function getAdminVideoImportStatus(
  sessionId: string,
): Promise<VideoImportStatus> {
  const res = await fetchWithAuth(
    `/api/v1/admin/video-imports/${sessionId}/status`,
  );
  return res.json();
}

/* ─── Prompt Studio (admin, create & share #524) ─────────────────────────────
 *
 * ADMIN-only surface (gated by `feature_flags.prompt_studio_enabled` +
 * `prompt_studio_roles`): author/upload a prompt, save versions, publish it to
 * a cohort. When the flag is off every call 403s — the page surfaces a
 * "not enabled" state. Backend: app/api/v1/admin/prompt_studio.py.
 */

export interface StudioJob {
  job_id: string;
  name: string;
  system_prompt: string;
}

export interface StudioPromptVersion {
  id: string;
  version_no: number;
  text: string;
  created_at: string;
}

export interface StudioPromptSummary {
  id: string;
  job_id: string;
  name: string;
  latest_version_no: number;
  created_at: string;
}

export interface StudioPromptDetail {
  id: string;
  job_id: string;
  name: string;
  created_at: string;
  versions: StudioPromptVersion[];
}

export type StudioScope = "SELF" | "ROLE" | "ALL";

export interface StudioPublication {
  id: string;
  job_id: string;
  version_id: string;
  version_no: number;
  scope: string;
  target_role: string | null;
  target_user_id: string | null;
  published_at: string;
}

export async function getStudioJobs(): Promise<StudioJob[]> {
  const res = await fetchWithAuth("/api/v1/admin/prompt-studio/jobs");
  return res.json();
}

export async function listStudioPrompts(): Promise<StudioPromptSummary[]> {
  const res = await fetchWithAuth("/api/v1/admin/prompt-studio/prompts");
  return res.json();
}

export async function getStudioPrompt(id: string): Promise<StudioPromptDetail> {
  const res = await fetchWithAuth(`/api/v1/admin/prompt-studio/prompts/${id}`);
  return res.json();
}

export async function createStudioPrompt(body: {
  job_id: string;
  name: string;
  text: string;
}): Promise<StudioPromptDetail> {
  const res = await fetchWithAuth("/api/v1/admin/prompt-studio/prompts", {
    method: "POST",
    body: JSON.stringify(body),
  });
  return res.json();
}

export async function saveStudioVersion(
  id: string,
  text: string,
): Promise<StudioPromptVersion> {
  const res = await fetchWithAuth(
    `/api/v1/admin/prompt-studio/prompts/${id}/versions`,
    { method: "POST", body: JSON.stringify({ text }) },
  );
  return res.json();
}

export async function publishStudioPrompt(
  id: string,
  body: { version_id: string; scope: StudioScope; target_role?: string },
): Promise<StudioPublication> {
  const res = await fetchWithAuth(
    `/api/v1/admin/prompt-studio/prompts/${id}/publish`,
    { method: "POST", body: JSON.stringify(body) },
  );
  return res.json();
}
