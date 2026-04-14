"use client";

import Header from "@/components/Header";
import {
  CheckCircleIcon,
  XCircleIcon,
} from "@heroicons/react/24/solid";

const placeholderReport = {
  total_sessions: 12,
  pass_count: 12,
  fail_count: 0,
  pass_rate: 100,
  sessions: [
    {
      session_id: "sess_001",
      clinician_name: "Dr. Perry Gdalevitch",
      date: "2026-04-10",
      total_frames: 48,
      masked_frames: 48,
      pass: true,
    },
    {
      session_id: "sess_002",
      clinician_name: "Dr. Marie Gdalevitch",
      date: "2026-04-10",
      total_frames: 32,
      masked_frames: 32,
      pass: true,
    },
    {
      session_id: "sess_003",
      clinician_name: "Dr. Perry Gdalevitch",
      date: "2026-04-09",
      total_frames: 55,
      masked_frames: 55,
      pass: true,
    },
  ],
};

export default function MaskingPage() {
  const report = placeholderReport;

  return (
    <>
      <Header
        title="PHI Masking Validation"
        subtitle="Per-session masking pass/fail status — 100% target"
      />

      <div className="p-6 lg:p-8">
        {/* Summary cards */}
        <div className="mb-8 grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-4">
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Total Sessions
            </p>
            <p className="mt-1 text-2xl font-bold text-navy">
              {report.total_sessions}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Passed
            </p>
            <p className="mt-1 text-2xl font-bold text-green-600">
              {report.pass_count}
            </p>
          </div>
          <div className="rounded-xl border border-gray-200 bg-white p-5 shadow-sm">
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Failed
            </p>
            <p className="mt-1 text-2xl font-bold text-red-600">
              {report.fail_count}
            </p>
          </div>
          <div
            className={`rounded-xl border p-5 shadow-sm ${
              report.pass_rate === 100
                ? "border-green-200 bg-green-50"
                : "border-red-200 bg-red-50"
            }`}
          >
            <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
              Pass Rate
            </p>
            <p
              className={`mt-1 text-2xl font-bold ${
                report.pass_rate === 100 ? "text-green-600" : "text-red-600"
              }`}
            >
              {report.pass_rate}%
            </p>
          </div>
        </div>

        {/* Per-session table */}
        <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
          <div className="overflow-x-auto">
            <table className="min-w-full divide-y divide-gray-200">
              <thead className="bg-gray-50">
                <tr>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Session
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Clinician
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Date
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Total Frames
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Masked
                  </th>
                  <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                    Status
                  </th>
                </tr>
              </thead>
              <tbody className="divide-y divide-gray-100">
                {report.sessions.map((s) => (
                  <tr key={s.session_id} className="hover:bg-gray-50">
                    <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                      {s.session_id}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-700">
                      {s.clinician_name}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                      {s.date}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                      {s.total_frames}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                      {s.masked_frames}
                    </td>
                    <td className="whitespace-nowrap px-4 py-3 text-sm">
                      {s.pass ? (
                        <span className="inline-flex items-center gap-1 text-green-600">
                          <CheckCircleIcon className="h-4 w-4" />
                          Pass
                        </span>
                      ) : (
                        <span className="inline-flex items-center gap-1 text-red-600">
                          <XCircleIcon className="h-4 w-4" />
                          Fail
                        </span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        <p className="mt-4 text-center text-xs text-gray-400">
          Showing placeholder data. Connect to the FastAPI backend to display
          live masking reports.
        </p>
      </div>
    </>
  );
}
