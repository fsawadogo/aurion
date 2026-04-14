"use client";

import { useState } from "react";
import Header from "@/components/Header";
import { PlusIcon } from "@heroicons/react/24/outline";
import type { UserRole } from "@/types";

interface PlaceholderUser {
  id: string;
  full_name: string;
  email: string;
  role: UserRole;
  is_active: boolean;
  voice_enrolled: boolean;
  last_login_at: string | null;
}

const placeholderUsers: PlaceholderUser[] = [
  {
    id: "u1",
    full_name: "Dr. Perry Gdalevitch",
    email: "perry@creoq.ca",
    role: "CLINICIAN",
    is_active: true,
    voice_enrolled: true,
    last_login_at: "2026-04-10T14:30:00Z",
  },
  {
    id: "u2",
    full_name: "Dr. Marie Gdalevitch",
    email: "marie@creoq.ca",
    role: "CLINICIAN",
    is_active: true,
    voice_enrolled: false,
    last_login_at: "2026-04-09T09:15:00Z",
  },
  {
    id: "u3",
    full_name: "Compliance Officer",
    email: "compliance@aurionclinical.com",
    role: "COMPLIANCE_OFFICER",
    is_active: true,
    voice_enrolled: false,
    last_login_at: null,
  },
  {
    id: "u4",
    full_name: "Eval Reviewer",
    email: "eval@aurionclinical.com",
    role: "EVAL_TEAM",
    is_active: true,
    voice_enrolled: false,
    last_login_at: null,
  },
  {
    id: "u5",
    full_name: "Faical Sawadogo",
    email: "admin@aurionclinical.com",
    role: "ADMIN",
    is_active: true,
    voice_enrolled: false,
    last_login_at: "2026-04-11T08:00:00Z",
  },
];

const roleBadgeColors: Record<UserRole, string> = {
  CLINICIAN: "bg-blue-100 text-blue-700",
  EVAL_TEAM: "bg-purple-100 text-purple-700",
  COMPLIANCE_OFFICER: "bg-emerald-100 text-emerald-700",
  CLINICAL_ADMIN: "bg-amber-100 text-amber-700",
  ADMIN: "bg-navy text-gold",
};

export default function UsersPage() {
  const [showCreateModal, setShowCreateModal] = useState(false);

  return (
    <>
      <Header
        title="User Management"
        subtitle="Manage clinician and admin accounts"
      />

      <div className="p-6 lg:p-8">
        {/* Actions */}
        <div className="mb-6 flex items-center justify-between">
          <p className="text-sm text-gray-500">
            {placeholderUsers.length} users
          </p>
          <button
            onClick={() => setShowCreateModal(true)}
            className="flex items-center gap-2 rounded-lg bg-gold px-4 py-2 text-sm font-medium text-navy transition-colors hover:bg-gold-600"
          >
            <PlusIcon className="h-4 w-4" />
            Create User
          </button>
        </div>

        {/* Table */}
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Name
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Email
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Role
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Status
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Voice Enrolled
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Last Login
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Actions
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {placeholderUsers.map((user) => (
                  <tr key={user.id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-medium text-gray-900">
                      {user.full_name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {user.email}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <span
                        className={`inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${
                          roleBadgeColors[user.role]
                        }`}
                      >
                        {user.role}
                      </span>
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {user.is_active ? (
                        <span className="inline-flex items-center gap-1 text-green-600">
                          <span className="h-2 w-2 rounded-full bg-green-500" />
                          Active
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-gray-400">
                          <span className="h-2 w-2 rounded-full bg-gray-300" />
                          Inactive
                        </span>
                      )}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {user.voice_enrolled ? "Yes" : "No"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-400">
                      {user.last_login_at
                        ? new Date(user.last_login_at).toLocaleDateString()
                        : "Never"}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      <button className="mr-2 text-gold-600 hover:text-gold-800">
                        Edit
                      </button>
                      {user.is_active && (
                        <button className="text-red-500 hover:text-red-700">
                          Deactivate
                        </button>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Create modal stub */}
        {showCreateModal && (
          <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/50">
            <div className="w-full max-w-md rounded-xl bg-white p-6 shadow-xl">
              <h3 className="mb-4 text-lg font-semibold text-navy">
                Create User
              </h3>
              <div className="space-y-4">
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    Full Name
                  </label>
                  <input
                    type="text"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    Email
                  </label>
                  <input
                    type="email"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                  />
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    Role
                  </label>
                  <select className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30">
                    <option value="CLINICIAN">CLINICIAN</option>
                    <option value="EVAL_TEAM">EVAL_TEAM</option>
                    <option value="COMPLIANCE_OFFICER">
                      COMPLIANCE_OFFICER
                    </option>
                    <option value="CLINICAL_ADMIN">CLINICAL_ADMIN</option>
                    <option value="ADMIN">ADMIN</option>
                  </select>
                </div>
                <div>
                  <label className="mb-1 block text-sm font-medium text-gray-700">
                    Password
                  </label>
                  <input
                    type="password"
                    className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-gold focus:outline-none focus:ring-2 focus:ring-gold/30"
                  />
                </div>
              </div>
              <div className="mt-6 flex justify-end gap-3">
                <button
                  onClick={() => setShowCreateModal(false)}
                  className="rounded-lg border border-gray-300 px-4 py-2 text-sm text-gray-600 hover:bg-gray-50"
                >
                  Cancel
                </button>
                <button className="rounded-lg bg-gold px-4 py-2 text-sm font-medium text-navy hover:bg-gold-600">
                  Create
                </button>
              </div>
            </div>
          </div>
        )}
      </div>
    </>
  );
}
