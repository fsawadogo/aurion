import type {
  AuditEvent,
  AuditFilters,
  AuthResponse,
  ConfigChangeEvent,
  CreateUserPayload,
  EvalScore,
  EvalSession,
  MaskingReport,
  MetricFilters,
  PaginatedResponse,
  PilotMetric,
  ProviderConfig,
  Session,
  SessionFilters,
  UpdateUserPayload,
  User,
} from "@/types";

const API_BASE = process.env.NEXT_PUBLIC_API_URL ?? "http://localhost:8000";

/* ─── Helpers ────────────────────────────────────────────────────────────── */

function getToken(): string | null {
  if (typeof document === "undefined") return null;
  const match = document.cookie.match(/(?:^|;\s*)aurion_token=([^;]*)/);
  return match ? decodeURIComponent(match[1]) : null;
}

function buildQuery(params: Record<string, unknown>): string {
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
  const token = getToken();
  const headers: Record<string, string> = {
    "Content-Type": "application/json",
    ...(options.headers as Record<string, string> | undefined),
  };
  if (token) {
    headers["Authorization"] = `Bearer ${token}`;
  }
  const response = await fetch(`${API_BASE}${path}`, {
    ...options,
    headers,
  });
  if (response.status === 401) {
    if (typeof window !== "undefined") {
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

export function logout(): void {
  document.cookie = "aurion_token=; path=/; max-age=0";
  window.location.href = "/login";
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
  const res = await fetchWithAuth(`/api/v1/admin/audit/session/${sessionId}`);
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
    `/api/v1/admin/masking${buildQuery(filters)}`,
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

/* ─── Sessions ───────────────────────────────────────────────────────────── */

export async function getSessions(
  filters: SessionFilters = {},
): Promise<PaginatedResponse<Session>> {
  const res = await fetchWithAuth(
    `/api/v1/admin/sessions${buildQuery(filters)}`,
  );
  return res.json();
}

export async function getSessionCompleteness(
  sessionId: string,
): Promise<Session> {
  const res = await fetchWithAuth(`/api/v1/admin/sessions/${sessionId}`);
  return res.json();
}

/* ─── Eval ───────────────────────────────────────────────────────────────── */

export async function getEvalSessions(): Promise<EvalSession[]> {
  const res = await fetchWithAuth("/api/v1/admin/eval/sessions");
  return res.json();
}

export async function getEvalSession(id: string): Promise<EvalSession> {
  const res = await fetchWithAuth(`/api/v1/admin/eval/sessions/${id}`);
  return res.json();
}

export async function submitEvalScore(
  id: string,
  scores: Omit<EvalScore, "scored_by" | "scored_at">,
): Promise<EvalSession> {
  const res = await fetchWithAuth(`/api/v1/admin/eval/sessions/${id}/score`, {
    method: "POST",
    body: JSON.stringify(scores),
  });
  return res.json();
}
