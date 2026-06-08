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
  MaskingReport,
  MediaDownloadUrls,
  MetricFilters,
  MetricTimeseriesFilters,
  MetricTimeseriesResponse,
  PaginatedResponse,
  PilotMetric,
  ProviderConfig,
  Session,
  SessionDetail,
  SessionFilters,
  UpdateFeatureFlagsResponse,
  UpdateUserPayload,
  User,
} from "@/types";
import {
  getStoredIdToken,
  refreshTokens,
  signOut as cognitoSignOut,
  tokenIsStale,
} from "@/lib/cognito";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* ─── Helpers ────────────────────────────────────────────────────────────── */

/** Resolve the bearer token for outgoing API requests.
 *
 * Preference order:
 *   1. Cognito id_token in sessionStorage (the new hosted-UI flow).
 *   2. Legacy `aurion_token` cookie (kept for one release so in-flight
 *      dev sessions don't get bounced mid-task).
 *
 * Returns null only if neither is present — the caller's request will
 * then fail with 401 and fetchWithAuth will route to /login.
 */
function getToken(): string | null {
  if (typeof window !== "undefined") {
    const cognito = getStoredIdToken();
    if (cognito) return cognito;
  }
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)aurion_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
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

export async function fetchWithAuth(
  path: string,
  options: RequestInit = {},
): Promise<Response> {
  // If the Cognito id_token is past its expiry, refresh proactively
  // so this request doesn't trigger the 401 retry path.
  if (typeof window !== "undefined" && tokenIsStale()) {
    await refreshTokens(); // null return = best-effort; downstream 401 handles it
  }

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

  // One silent refresh + retry on 401 — if the refresh works the
  // user never sees the redirect.
  if (response.status === 401 && typeof window !== "undefined") {
    const refreshed = await refreshTokens();
    if (refreshed) {
      response = await fetch(`${API_BASE}${path}`, {
        ...options,
        headers: buildHeaders(),
      });
    }
    if (response.status === 401) {
      window.location.href = "/login";
    }
  }

  if (!response.ok) {
    const body = await response.text();
    throw new Error(`API ${response.status}: ${body}`);
  }
  return response;
}

/* ─── Auth ───────────────────────────────────────────────────────────────── */

export async function login(
  email: string,
  password: string,
): Promise<AuthResponse> {
  const res = await fetch(`${API_BASE}/api/v1/auth/login`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!res.ok) {
    // Surface the backend `detail` string when present (FastAPI wraps
    // errors as { detail: "..." }) so callers can match on clean copy —
    // e.g. the 429 lockout message — rather than raw JSON. Falls back to
    // the raw body for non-JSON responses.
    const body = await res.text();
    let detail = body;
    try {
      const parsed = JSON.parse(body) as { detail?: unknown };
      if (parsed && typeof parsed.detail === "string") detail = parsed.detail;
    } catch {
      /* non-JSON body — keep the raw text */
    }
    throw new Error(`Login failed: ${detail}`);
  }
  const data: AuthResponse = await res.json();
  document.cookie = `aurion_token=${encodeURIComponent(data.access_token)}; path=/; SameSite=Strict; max-age=86400`;
  return data;
}

/** Sign out. For Cognito hosted-UI sessions, redirects through Cognito's
 * /logout so the server-side session terminates too. For native JWT
 * sessions (no Cognito tokens present), just clears the cookie and bounces
 * to /login — Cognito's /logout would otherwise force a redirect through
 * an account they never had. */
export function logout(): void {
  document.cookie = "aurion_token=; path=/; max-age=0";
  if (typeof window === "undefined") return;
  if (getStoredIdToken()) {
    cognitoSignOut();
  } else {
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
