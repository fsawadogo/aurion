"use client";

import { CheckCircle2, Plus, ShieldCheck, Stethoscope, Users as UsersIcon, XCircle } from "lucide-react";
import { useEffect, useMemo, useState } from "react";
import Header from "@/components/Header";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Modal from "@/components/ui/Modal";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getUsers, createUser, updateUser, humanizeError} from "@/lib/api";
import { nameInitials } from "@/lib/session-format";
import type { User, UserRole, CreateUserPayload } from "@/types";

const roleBadgeVariant: Record<UserRole, "success" | "warning" | "error" | "info" | "neutral"> = {
  ADMIN: "warning",
  CLINICIAN: "info",
  EVAL_TEAM: "success",
  COMPLIANCE_OFFICER: "neutral",
  CLINICAL_ADMIN: "info",
};

// Human-readable role labels — the API returns raw enum values
// (EVAL_TEAM, COMPLIANCE_OFFICER) which shouldn't surface verbatim.
const roleLabel: Record<string, string> = {
  ADMIN: "Admin",
  CLINICIAN: "Clinician",
  EVAL_TEAM: "Eval Team",
  COMPLIANCE_OFFICER: "Compliance Officer",
  CLINICAL_ADMIN: "Clinical Admin",
};

/** Display name with a graceful fallback to the email local-part when a
 * user has no full_name set (avoids a blank Name cell). */
function displayName(user: User): string {
  return user.full_name?.trim() || user.email.split("@")[0];
}

function relativeTime(dateStr: string | null): string {
  if (!dateStr) return "Never";
  const now = Date.now();
  const then = new Date(dateStr).getTime();
  const diffMs = now - then;
  if (diffMs < 0) return "just now";
  const seconds = Math.floor(diffMs / 1000);
  if (seconds < 60) return "just now";
  const minutes = Math.floor(seconds / 60);
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.floor(minutes / 60);
  if (hours < 24) return `${hours}h ago`;
  const days = Math.floor(hours / 24);
  if (days < 30) return `${days}d ago`;
  const months = Math.floor(days / 30);
  return `${months}mo ago`;
}

export default function UsersPage() {
  const [users, setUsers] = useState<User[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [showCreateModal, setShowCreateModal] = useState(false);

  // Create form state
  const [newName, setNewName] = useState("");
  const [newEmail, setNewEmail] = useState("");
  const [newRole, setNewRole] = useState<UserRole>("CLINICIAN");
  const [newPassword, setNewPassword] = useState("");
  const [creating, setCreating] = useState(false);

  async function fetchUsers() {
    setLoading(true);
    setError(null);
    try {
      const data = await getUsers();
      setUsers(data);
    } catch (err) {
      setError(humanizeError(err, "Failed to load users"));
    } finally {
      setLoading(false);
    }
  }

  useEffect(() => {
    fetchUsers();
  }, []);

  // Summary stats for the header cards (Stitch redesign) — derived client-side
  // from the loaded list; the pilot scale (<200 users) makes a rollup endpoint
  // overkill. "MFA active" counts enrolled (not merely required) accounts.
  const stats = useMemo(() => ({
    total: users.length,
    clinicians: users.filter((u) => u.role === "CLINICIAN").length,
    mfaActive: users.filter((u) => u.mfa_enrolled).length,
  }), [users]);

  async function handleCreate() {
    setCreating(true);
    try {
      const payload: CreateUserPayload = {
        full_name: newName,
        email: newEmail,
        role: newRole,
        password: newPassword,
      };
      await createUser(payload);
      setShowCreateModal(false);
      setNewName("");
      setNewEmail("");
      setNewRole("CLINICIAN");
      setNewPassword("");
      await fetchUsers();
    } catch (err) {
      setError(humanizeError(err, "Failed to create user"));
    } finally {
      setCreating(false);
    }
  }

  async function handleSetActive(userId: string, isActive: boolean) {
    if (
      !isActive &&
      !window.confirm(
        "Deactivate this account? The user will be blocked on their next request.",
      )
    ) {
      return;
    }
    try {
      await updateUser(userId, { is_active: isActive });
      await fetchUsers();
    } catch (err) {
      setError(humanizeError(err, "Failed to update user"));
    }
  }

  async function handleSetMfaRequired(userId: string, required: boolean) {
    try {
      // #397: when an admin requires MFA, the user must enroll TOTP
      // before their next login completes (the backend returns
      // enroll_required instead of a session).
      await updateUser(userId, { mfa_required: required });
      await fetchUsers();
    } catch (err) {
      setError(humanizeError(err, "Failed to update user"));
    }
  }

  // #590 — grant/revoke the per-user prompt-testing capability (re-run notes
  // with a different template on own uploads). Orthogonal to role; the backend
  // gates the regenerate endpoint on this flag.
  async function handleSetPromptTestingEnabled(
    userId: string,
    enabled: boolean,
  ) {
    try {
      await updateUser(userId, { prompt_testing_enabled: enabled });
      await fetchUsers();
    } catch (err) {
      setError(humanizeError(err, "Failed to update user"));
    }
  }

  return (
    <>
      <Header
        title="User Management"
        subtitle="Manage clinician and admin accounts"
        actions={
          <Button variant="primary" size="sm" onClick={() => setShowCreateModal(true)}>
            <Plus className="h-4 w-4" />
            Create User
          </Button>
        }
      />

      <div className="p-6 lg:p-8">
        {error && (
          <div className="mb-6 flex items-start gap-2 rounded-lg bg-red-50 px-4 py-3 text-sm text-red-700 ring-1 ring-inset ring-red-600/10">
            <span className="flex-1">{error}</span>
            <button onClick={() => setError(null)} className="text-red-400 hover:text-red-600 text-xs font-medium">
              Dismiss
            </button>
          </div>
        )}

        {/* Summary stat cards (Stitch redesign) */}
        <div className="mb-6 grid grid-cols-1 gap-3 sm:grid-cols-3">
          <StatCard
            icon={<UsersIcon className="h-5 w-5 text-navy-500" />}
            label="Total users"
            value={stats.total}
            loading={loading}
          />
          <StatCard
            icon={<Stethoscope className="h-5 w-5 text-blue-500" />}
            label="Clinicians"
            value={stats.clinicians}
            loading={loading}
          />
          <StatCard
            icon={<ShieldCheck className="h-5 w-5 text-emerald-600" />}
            label="MFA active"
            value={stats.mfaActive}
            loading={loading}
          />
        </div>

        <p className="mb-4 text-xs text-gray-400">
          {loading ? "Loading..." : `${users.length} user${users.length === 1 ? "" : "s"}`}
        </p>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200/60 bg-white shadow-card">
          <div className="overflow-x-auto">
            <table className="min-w-full">
              <thead>
                <tr className="border-b border-gray-100 bg-gray-50/80">
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">User</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Role</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Status</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Voice</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Last Login</th>
                  <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Actions</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-50">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-6">
                      <LoadingSkeleton lines={4} />
                    </td>
                  </tr>
                ) : users.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="px-4 py-12 text-center">
                      <p className="text-sm text-gray-400">No users found.</p>
                    </td>
                  </tr>
                ) : (
                  users.map((user) => (
                    <tr key={user.id} className="transition-colors hover:bg-gray-50/80">
                      <td className="whitespace-nowrap px-4 py-3">
                        <div className="flex items-center gap-2.5">
                          <span className="flex h-9 w-9 shrink-0 items-center justify-center rounded-full bg-navy-50 text-[11px] font-semibold text-navy-700 ring-1 ring-inset ring-navy-100">
                            {nameInitials(displayName(user))}
                          </span>
                          <div className="min-w-0">
                            <div className="text-sm font-medium text-navy-800">{displayName(user)}</div>
                            <div className="text-xs text-gray-500">{user.email}</div>
                          </div>
                        </div>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Badge variant={roleBadgeVariant[user.role as UserRole] ?? "neutral"}>
                          {roleLabel[user.role] ?? user.role}
                        </Badge>
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {user.is_active ? (
                          <Badge variant="success" dot>Active</Badge>
                        ) : (
                          <Badge variant="neutral" dot>Inactive</Badge>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        {user.voice_enrolled ? (
                          <span className="inline-flex items-center gap-1.5 text-xs font-medium text-emerald-600">
                            <CheckCircle2 className="h-4 w-4" aria-hidden />
                            Enrolled
                          </span>
                        ) : (
                          <span className="inline-flex items-center gap-1.5 text-xs text-gray-400">
                            <XCircle className="h-4 w-4 text-gray-300" aria-hidden />
                            Not enrolled
                          </span>
                        )}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-xs text-gray-400">
                        {relativeTime(user.last_login_at)}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() => handleSetMfaRequired(user.id, !user.mfa_required)}
                          data-testid={`mfa-toggle-${user.id}`}
                          className={
                            user.mfa_required
                              ? "text-gold-700 hover:bg-gold-50"
                              : "text-gray-500 hover:bg-gray-50"
                          }
                          title={
                            user.mfa_required
                              ? "MFA required — user must enroll TOTP to sign in"
                              : "MFA optional — click to require it"
                          }
                        >
                          {user.mfa_required ? "MFA: required" : "MFA: optional"}
                        </Button>
                        <Button
                          variant="ghost"
                          size="sm"
                          onClick={() =>
                            handleSetPromptTestingEnabled(
                              user.id,
                              !user.prompt_testing_enabled,
                            )
                          }
                          data-testid={`prompt-testing-toggle-${user.id}`}
                          className={
                            user.prompt_testing_enabled
                              ? "text-gold-700 hover:bg-gold-50"
                              : "text-gray-500 hover:bg-gray-50"
                          }
                          title={
                            user.prompt_testing_enabled
                              ? "Prompt testing on — user can re-run notes with a different template"
                              : "Prompt testing off — click to grant"
                          }
                        >
                          {user.prompt_testing_enabled
                            ? "Prompt testing: on"
                            : "Prompt testing: off"}
                        </Button>
                        {user.is_active ? (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSetActive(user.id, false)}
                            className="text-red-500 hover:text-red-700 hover:bg-red-50"
                          >
                            Deactivate
                          </Button>
                        ) : (
                          <Button
                            variant="ghost"
                            size="sm"
                            onClick={() => handleSetActive(user.id, true)}
                            className="text-emerald-600 hover:text-emerald-700 hover:bg-emerald-50"
                          >
                            Activate
                          </Button>
                        )}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create modal */}
        <Modal
          isOpen={showCreateModal}
          onClose={() => setShowCreateModal(false)}
          title="Create User"
          footer={
            <>
              <Button variant="secondary" onClick={() => setShowCreateModal(false)}>
                Cancel
              </Button>
              <Button
                variant="primary"
                loading={creating}
                disabled={!newName || !newEmail || !newPassword}
                onClick={handleCreate}
              >
                Create
              </Button>
            </>
          }
        >
          <div className="space-y-4">
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-700">Full Name</label>
              <input
                type="text"
                value={newName}
                onChange={(e) => setNewName(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                placeholder="Dr. Jane Smith"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-700">Email</label>
              <input
                type="email"
                value={newEmail}
                onChange={(e) => setNewEmail(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
                placeholder="jane@aurionclinical.com"
              />
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-700">Role</label>
              <select
                value={newRole}
                onChange={(e) => setNewRole(e.target.value as UserRole)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              >
                <option value="CLINICIAN">Clinician</option>
                <option value="EVAL_TEAM">Eval Team</option>
                <option value="COMPLIANCE_OFFICER">Compliance Officer</option>
                <option value="CLINICAL_ADMIN">Clinical Admin</option>
                <option value="ADMIN">Admin</option>
              </select>
            </div>
            <div>
              <label className="mb-1.5 block text-sm font-medium text-gray-700">Password</label>
              <input
                type="password"
                value={newPassword}
                onChange={(e) => setNewPassword(e.target.value)}
                className="w-full rounded-lg border border-gray-200 bg-gray-50/50 px-3 py-2 text-sm transition-colors focus:border-gold-400 focus:bg-white focus:outline-none focus:ring-2 focus:ring-gold-100"
              />
            </div>
          </div>
        </Modal>
      </div>
    </>
  );
}

/** Summary stat card for the User Management header (Stitch redesign).
 * bg-white / text-navy / border-gray adapt to dark mode via the html.dark
 * utility remap in globals.css. */
function StatCard({
  icon,
  label,
  value,
  loading,
}: {
  icon: React.ReactNode;
  label: string;
  value: number;
  loading: boolean;
}) {
  return (
    <div className="rounded-xl border border-gray-200/60 bg-white p-4 shadow-card">
      <div className="flex items-center justify-between">
        <span className="inline-flex h-9 w-9 items-center justify-center rounded-full bg-gray-50">
          {icon}
        </span>
        <span className="text-2xl font-semibold tabular-nums text-navy-800">
          {loading ? "—" : value}
        </span>
      </div>
      <p className="mt-2 text-[11px] font-semibold uppercase tracking-wider text-gray-400">
        {label}
      </p>
    </div>
  );
}
