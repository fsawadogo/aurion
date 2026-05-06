"use client";

import { useEffect, useState } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import {
  CpuChipIcon,
  AdjustmentsHorizontalIcon,
  FlagIcon,
  ClockIcon,
} from "@heroicons/react/24/outline";
import { getConfig, getConfigHistory } from "@/lib/api";
import type { ProviderConfig, ConfigChangeEvent } from "@/types";

const defaultConfig: ProviderConfig = {
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

function ToggleSwitch({ enabled }: { enabled: boolean }) {
  return (
    <div
      className={`relative inline-flex h-5 w-9 items-center rounded-full transition-colors ${
        enabled ? "bg-gold-500" : "bg-gray-200"
      }`}
    >
      <span
        className={`inline-block h-3.5 w-3.5 transform rounded-full bg-white shadow-sm transition-transform ${
          enabled ? "translate-x-[18px]" : "translate-x-[3px]"
        }`}
      />
    </div>
  );
}

function ConfigRow({ label, value }: { label: string; value: string | number }) {
  return (
    <div className="flex items-center justify-between py-1.5">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="text-sm font-medium text-navy-700">{value}</span>
    </div>
  );
}

export default function ConfigPage() {
  const [cfg, setCfg] = useState<ProviderConfig>(defaultConfig);
  const [history, setHistory] = useState<ConfigChangeEvent[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  useEffect(() => {
    async function fetchData() {
      setLoading(true);
      setError(null);
      try {
        const [configData, historyData] = await Promise.all([
          getConfig(),
          getConfigHistory(),
        ]);
        setCfg(configData);
        setHistory(historyData);
      } catch (err) {
        setError(
          err instanceof Error ? err.message : "Failed to load configuration",
        );
      } finally {
        setLoading(false);
      }
    }
    fetchData();
  }, []);

  return (
    <>
      <Header
        title="Configuration"
        subtitle="Read-only AppConfig state"
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

        {loading && <LoadingSkeleton lines={4} className="mb-6" />}

        <div className="grid grid-cols-1 gap-6 lg:grid-cols-2 stagger-children">
          {/* Active Providers */}
          <Card hoverable>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="rounded-lg bg-gold-50 p-2">
                <CpuChipIcon className="h-4 w-4 text-gold-600" />
              </div>
              <h2 className="text-sm font-semibold text-navy-700">
                Active Providers
              </h2>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Transcription</span>
                <Badge variant="info">{cfg.providers.transcription}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Note Generation</span>
                <Badge variant="info">{cfg.providers.note_generation}</Badge>
              </div>
              <div className="flex items-center justify-between">
                <span className="text-sm text-gray-500">Vision</span>
                <Badge variant="info">{cfg.providers.vision}</Badge>
              </div>
            </div>
          </Card>

          {/* Model Parameters */}
          <Card hoverable>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="rounded-lg bg-gold-50 p-2">
                <AdjustmentsHorizontalIcon className="h-4 w-4 text-gold-600" />
              </div>
              <h2 className="text-sm font-semibold text-navy-700">
                Model Parameters
              </h2>
            </div>
            <div className="space-y-3">
              <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                Note Generation
              </p>
              <div className="flex gap-4 text-sm">
                <span className="text-gray-500">
                  Temp: <span className="font-medium text-navy-700">{cfg.model_params.note_generation.temperature}</span>
                </span>
                <span className="text-gray-500">
                  Max tokens: <span className="font-medium text-navy-700">{cfg.model_params.note_generation.max_tokens}</span>
                </span>
              </div>
              <div className="border-t border-gray-100 pt-3">
                <p className="text-[11px] font-medium uppercase tracking-wider text-gray-400">
                  Vision
                </p>
              </div>
              <div className="flex flex-wrap gap-4 text-sm">
                <span className="text-gray-500">
                  Temp: <span className="font-medium text-navy-700">{cfg.model_params.vision.temperature}</span>
                </span>
                <span className="text-gray-500">
                  Max tokens: <span className="font-medium text-navy-700">{cfg.model_params.vision.max_tokens}</span>
                </span>
                <span className="text-gray-500">
                  Confidence: <span className="font-medium text-navy-700">{cfg.model_params.vision.confidence_threshold}</span>
                </span>
              </div>
            </div>
          </Card>

          {/* Pipeline Settings */}
          <Card hoverable>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="rounded-lg bg-gold-50 p-2">
                <ClockIcon className="h-4 w-4 text-gold-600" />
              </div>
              <h2 className="text-sm font-semibold text-navy-700">
                Pipeline Settings
              </h2>
            </div>
            <div className="divide-y divide-gray-50">
              <ConfigRow label="Stage 1 skip window" value={`${cfg.pipeline.stage1_skip_window_seconds}s`} />
              <ConfigRow label="Frame window (clinic)" value={`${cfg.pipeline.frame_window_clinic_ms}ms`} />
              <ConfigRow label="Frame window (procedural)" value={`${cfg.pipeline.frame_window_procedural_ms}ms`} />
              <ConfigRow label="Screen capture FPS" value={cfg.pipeline.screen_capture_fps} />
              <ConfigRow label="Video capture FPS" value={cfg.pipeline.video_capture_fps} />
            </div>
          </Card>

          {/* Feature Flags */}
          <Card hoverable>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="rounded-lg bg-gold-50 p-2">
                <FlagIcon className="h-4 w-4 text-gold-600" />
              </div>
              <h2 className="text-sm font-semibold text-navy-700">
                Feature Flags
              </h2>
            </div>
            <div className="space-y-3">
              {Object.entries(cfg.feature_flags).map(([key, value]) => (
                <div key={key} className="flex items-center justify-between">
                  <span className="text-sm capitalize text-gray-500">
                    {key.replace(/_/g, " ")}
                  </span>
                  <ToggleSwitch enabled={value} />
                </div>
              ))}
            </div>
          </Card>
        </div>

        {/* Config change history */}
        <div className="mt-8">
          <h2 className="mb-4 text-sm font-semibold uppercase tracking-wider text-gray-400">
            Change History
          </h2>
          <div className="overflow-hidden rounded-xl border border-gray-200/60 bg-white shadow-card">
            <div className="overflow-x-auto">
              <table className="min-w-full">
                <thead>
                  <tr className="border-b border-gray-100 bg-gray-50/80">
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Timestamp</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Changed By</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Previous</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">New</th>
                    <th className="px-4 py-3 text-left text-[11px] font-semibold uppercase tracking-wider text-gray-400">Version</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-gray-50">
                  {history.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-12 text-center">
                        <p className="text-sm text-gray-400">No configuration changes recorded yet.</p>
                      </td>
                    </tr>
                  ) : (
                    history.map((h) => (
                      <tr key={h.id} className="transition-colors hover:bg-gray-50/80">
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-500">
                          {new Date(h.changed_at).toLocaleString()}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm text-gray-600">
                          {h.changed_by}
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <code className="rounded bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500">
                            {JSON.stringify(h.previous_config).slice(0, 60)}
                          </code>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <code className="rounded bg-gray-50 px-1.5 py-0.5 text-xs text-gray-500">
                            {JSON.stringify(h.new_config).slice(0, 60)}
                          </code>
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant="info">v{h.appconfig_version}</Badge>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        </div>

        <p className="mt-6 text-center text-[11px] text-gray-400">
          Read-only display. Provider switching is available via the admin API only.
        </p>
      </div>
    </>
  );
}
