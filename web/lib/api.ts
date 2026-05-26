import type {
  AuditEvent,
  AuditFilters,
  AuthResponse,
  ConfigChangeEvent,
  CreateUserPayload,
  CurrentUser,
  EvalAssignee,
  EvalScoreSubmission,
  EvalSession,
  EvalSessionDetail,
  MaskingReport,
  MetricFilters,
  MetricTimeseriesFilters,
  MetricTimeseriesResponse,
  PaginatedResponse,
  PilotMetric,
  ProviderConfig,
  Session,
  SessionDetail,
  SessionFilters,
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
    const body = await res.text();
    throw new Error(`Login failed: ${body}`);
  }
  const data: AuthResponse = await res.json();
  document.cookie = `aurion_token=${encodeURIComponent(data.access_token)}; path=/; SameSite=Strict; max-age=86400`;
  return data;
}

/** Sign out via Cognito's /logout endpoint so the hosted-UI session
 * terminates server-side too. Also clears the legacy `aurion_token`
 * cookie for any in-flight dev sessions. */
export function logout(): void {
  document.cookie = "aurion_token=; path=/; max-age=0";
  cognitoSignOut();
}

export async function getMe(): Promise<CurrentUser> {
  const res = await fetchWithAuth("/api/v1/auth/me");
  return res.json();
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
