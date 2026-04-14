"use client";

import Header from "@/components/Header";
import {
  CpuChipIcon,
  AdjustmentsHorizontalIcon,
  FlagIcon,
  ClockIcon,
} from "@heroicons/react/24/outline";

const placeholderConfig = {
  providers: {
    transcription: "whisper",
    note_generation: "anthropic",
    vision: "openai",
  },
  model_params: {
    note_generation: { temperature: 0.1, max_tokens: 2000 },
    vision: { temperature: 0.1, max_tokens: 500, confidence_threshold: "medium" },
  },
  pipeline: {
    stage1_skip_window_seconds: 60,
    frame_window_clinic_ms: 3000,
    frame_window_procedural_ms: 7000,
    screen_capture_fps: 2,
    video_capture_fps: 1,
  },
  feature_flags: {
    screen_capture_enabled: true,
    note_versioning_enabled: true,
    session_pause_resume_enabled: true,
    per_session_provider_override: true,
  },
};

const placeholderHistory = [
  {
    id: "ch_001",
    changed_by: "admin@aurionclinical.com",
    changed_at: "2026-04-10T16:00:00Z",
    field: "providers.note_generation",
    previous: "openai",
    new_value: "anthropic",
    version: 3,
  },
  {
    id: "ch_002",
    changed_by: "admin@aurionclinical.com",
    changed_at: "2026-04-08T10:30:00Z",
    field: "providers.vision",
    previous: "anthropic",
    new_value: "openai",
    version: 2,
  },
];

function ProviderBadge({ name }: { name: string }) {
  const colors: Record<string, string> = {
    whisper: "bg-green-100 text-green-700",
    assemblyai: "bg-blue-100 text-blue-700",
    openai: "bg-emerald-100 text-emerald-700",
    anthropic: "bg-orange-100 text-orange-700",
    gemini: "bg-purple-100 text-purple-700",
  };
  return (
    <span
      className={`inline-block rounded-full px-3 py-1 text-sm font-medium ${
        colors[name] ?? "bg-gray-100 text-gray-700"
      }`}
    >
      {name}
    </span>
  );
}

export default function ConfigPage() {
  const cfg = placeholderConfig;

  return (
    <>
      <Header
        title="Provider Configuration"
        subtitle="Read-only view of current AppConfig state"
      />

      <div className="p-6 lg:p-8">
        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2">
          {/* Active Providers */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <CpuChipIcon className="h-5 w-5 text-gold" />
              <h2 className="text-base font-semibold text-navy">
                Active Providers
              </h2>
            </div>
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Transcription</span>
                <ProviderBadge name={cfg.providers.transcription} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Note Generation</span>
                <ProviderBadge name={cfg.providers.note_generation} />
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-600">Vision</span>
                <ProviderBadge name={cfg.providers.vision} />
              </div>
            </div>
          </div>

          {/* Model Parameters */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <AdjustmentsHorizontalIcon className="h-5 w-5 text-gold" />
              <h2 className="text-base font-semibold text-navy">
                Model Parameters
              </h2>
            </div>
            <div className="space-y-3">
              <p className="text-xs font-medium uppercase tracking-wider text-gray-400">
                Note Generation
              </p>
              <div className="flex gap-6 text-sm text-gray-600">
                <span>
                  Temperature:{" "}
                  <strong>{cfg.model_params.note_generation.temperature}</strong>
                </span>
                <span>
                  Max tokens:{" "}
                  <strong>{cfg.model_params.note_generation.max_tokens}</strong>
                </span>
              </div>
              <p className="mt-2 text-xs font-medium uppercase tracking-wider text-gray-400">
                Vision
              </p>
              <div className="flex gap-6 text-sm text-gray-600">
                <span>
                  Temperature:{" "}
                  <strong>{cfg.model_params.vision.temperature}</strong>
                </span>
                <span>
                  Max tokens:{" "}
                  <strong>{cfg.model_params.vision.max_tokens}</strong>
                </span>
                <span>
                  Confidence:{" "}
                  <strong>
                    {cfg.model_params.vision.confidence_threshold}
                  </strong>
                </span>
              </div>
            </div>
          </div>

          {/* Pipeline Settings */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <ClockIcon className="h-5 w-5 text-gold" />
              <h2 className="text-base font-semibold text-navy">
                Pipeline Settings
              </h2>
            </div>
            <div className="space-y-2 text-sm text-gray-600">
              <div className="flex justify-between">
                <span>Stage 1 skip window</span>
                <strong>{cfg.pipeline.stage1_skip_window_seconds}s</strong>
              </div>
              <div className="flex justify-between">
                <span>Frame window (clinic)</span>
                <strong>{cfg.pipeline.frame_window_clinic_ms}ms</strong>
              </div>
              <div className="flex justify-between">
                <span>Frame window (procedural)</span>
                <strong>{cfg.pipeline.frame_window_procedural_ms}ms</strong>
              </div>
              <div className="flex justify-between">
                <span>Screen capture FPS</span>
                <strong>{cfg.pipeline.screen_capture_fps}</strong>
              </div>
              <div className="flex justify-between">
                <span>Video capture FPS</span>
                <strong>{cfg.pipeline.video_capture_fps}</strong>
              </div>
            </div>
          </div>

          {/* Feature Flags */}
          <div className="rounded-xl border border-gray-200 bg-white p-6 shadow-sm">
            <div className="mb-4 flex items-center gap-2">
              <FlagIcon className="h-5 w-5 text-gold" />
              <h2 className="text-base font-semibold text-navy">
                Feature Flags
              </h2>
            </div>
            <div className="space-y-3">
              {Object.entries(cfg.feature_flags).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm text-gray-600">
                    {key.replace(/_/g, " ")}
                  </span>
                  <span
                    className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${
                      value
                        ? "bg-green-100 text-green-700"
                        : "bg-red-100 text-red-700"
                    }`}
                  >
                    {value ? "Enabled" : "Disabled"}
                  </span>
                </div>
              ))}
            </div>
          </div>
        </div>

        {/* Config change history */}
        <div className="mt-8">
          <h2 className="mb-4 text-base font-semibold text-navy">
            Configuration Change History
          </h2>
          <div className="overflow-hidden rounded-xl border border-gray-200 bg-white shadow-sm">
            <div className="overflow-x-auto">
              <table className="min-w-full divide-y divide-gray-200">
                <thead className="bg-gray-50">
                  <tr>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                      Timestamp
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                      Changed By
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                      Field
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                      Previous
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                      New
                    </th>
                    <th className="px-4 py-3 text-left text-xs font-semibold uppercase tracking-wider text-gray-500">
                      Version
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-100">
                  {placeholderHistory.map((h) => (
                    <tr key={h.id} className="hover:bg-gray-50">
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {new Date(h.changed_at).toLocaleString()}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                        {h.changed_by}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm font-mono text-gray-500">
                        {h.field}
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <ProviderBadge name={h.previous} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm">
                        <ProviderBadge name={h.new_value} />
                      </td>
                      <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                        v{h.version}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <p className="mt-4 text-center text-xs text-gray-400">
          Read-only display. Provider switching is available via the admin API
          only.
        </p>
      </div>
    </>
  );
}
