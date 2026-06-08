"use client";

import { Clock, Cpu, Flag, History, SlidersHorizontal } from "lucide-react";
import { useEffect, useState } from "react";
import Header from "@/components/Header";
import Card from "@/components/ui/Card";
import Badge from "@/components/ui/Badge";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import { getConfig, getConfigHistory, humanizeError} from "@/lib/api";
import { abbreviateName, formatRelative, nameInitials } from "@/lib/session-format";
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
    <div className="flex items-center justify-between gap-4 py-1.5">
      <span className="text-sm text-gray-500">{label}</span>
      <span className="font-mono text-sm font-medium tabular-nums text-navy-700">
        {value}
      </span>
    </div>
  );
}

/** Title-cases each dot-separated segment of a config key path for display,
 * keeping the raw path available via the caller's `title` attribute.
 *   "providers.note_generation" → "Providers · Note generation" */
function humanizeConfigPath(path: string): string {
  return path
    .split(".")
    .map((seg) =>
      seg.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase()),
    )
    .join(" · ");
}

/** Flattens a (partial) config object into leaf [dottedPath, value] pairs so
 * a change event renders as readable key/value chips instead of raw JSON. */
function flattenConfig(
  obj: unknown,
  prefix = "",
): Array<[string, string]> {
  if (obj === null || typeof obj !== "object") return [];
  const out: Array<[string, string]> = [];
  for (const [key, val] of Object.entries(obj as Record<string, unknown>)) {
    const path = prefix ? `${prefix}.${key}` : key;
    if (val !== null && typeof val === "object" && !Array.isArray(val)) {
      out.push(...flattenConfig(val, path));
    } else {
      out.push([path, String(val)]);
    }
  }
  return out;
}

/** Renders a config snapshot as stacked key/value rows. Falls back to a muted
 * em dash for empty snapshots so the cell never shows raw `{}`. */
function ConfigDiff({ config }: { config: Partial<ProviderConfig> }) {
  const entries = flattenConfig(config);
  if (entries.length === 0) {
    return <span className="text-gray-300">—</span>;
  }
  return (
    <div className="space-y-1" title={JSON.stringify(config)}>
      {entries.map(([path, value]) => (
        <div key={path} className="flex items-baseline gap-2">
          <span className="text-xs text-gray-400">{humanizeConfigPath(path)}</span>
          <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-xs tracking-tight text-gray-600">
            {value}
          </code>
        </div>
      ))}
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
          humanizeError(err, "Failed to load configuration"),
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
                <Cpu className="h-4 w-4 text-gold-600" />
              </div>
              <h2 className="text-sm font-semibold text-navy-700">
                Active Providers
              </h2>
            </div>
            <div className="space-y-3">
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-gray-500">Transcription</span>
                <Badge variant="info" className="font-mono">{cfg.providers.transcription}</Badge>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-gray-500">Note Generation</span>
                <Badge variant="info" className="font-mono">{cfg.providers.note_generation}</Badge>
              </div>
              <div className="flex items-center justify-between gap-4">
                <span className="text-sm text-gray-500">Vision</span>
                <Badge variant="info" className="font-mono">{cfg.providers.vision}</Badge>
              </div>
            </div>
          </Card>

          {/* Model Parameters */}
          <Card hoverable>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="rounded-lg bg-gold-50 p-2">
                <SlidersHorizontal className="h-4 w-4 text-gold-600" />
              </div>
              <h2 className="text-sm font-semibold text-navy-700">
                Model Parameters
              </h2>
            </div>
            <div className="divide-y divide-gray-50">
              <div className="pb-2">
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-gray-400">
                  Note Generation
                </p>
                <ConfigRow label="Temperature" value={cfg.model_params.note_generation.temperature} />
                <ConfigRow label="Max tokens" value={cfg.model_params.note_generation.max_tokens} />
              </div>
              <div className="pt-2">
                <p className="mb-1 text-[11px] font-medium uppercase tracking-wider text-gray-400">
                  Vision
                </p>
                <ConfigRow label="Temperature" value={cfg.model_params.vision.temperature} />
                <ConfigRow label="Max tokens" value={cfg.model_params.vision.max_tokens} />
                <ConfigRow label="Confidence threshold" value={cfg.model_params.vision.confidence_threshold} />
              </div>
            </div>
          </Card>

          {/* Pipeline Settings */}
          <Card hoverable>
            <div className="mb-4 flex items-center gap-2.5">
              <div className="rounded-lg bg-gold-50 p-2">
                <Clock className="h-4 w-4 text-gold-600" />
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
                <Flag className="h-4 w-4 text-gold-600" />
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
                        <div className="flex flex-col items-center gap-2">
                          <div className="rounded-full bg-gray-50 p-2.5 ring-1 ring-inset ring-gray-100">
                            <History className="h-5 w-5 text-gray-300" />
                          </div>
                          <p className="text-sm text-gray-400">No configuration changes recorded yet.</p>
                        </div>
                      </td>
                    </tr>
                  ) : (
                    history.map((h) => (
                      <tr key={h.id} className="align-top transition-colors hover:bg-gray-50/80">
                        <td
                          className="whitespace-nowrap px-4 py-3 text-sm text-gray-500"
                          title={new Date(h.changed_at).toLocaleString()}
                        >
                          {formatRelative(h.changed_at)}
                        </td>
                        <td className="whitespace-nowrap px-4 py-3">
                          <div
                            className="flex items-center gap-2.5"
                            title={h.changed_by || undefined}
                          >
                            <span className="flex h-7 w-7 shrink-0 items-center justify-center rounded-full bg-navy-50 text-[10px] font-semibold text-navy-700 ring-1 ring-inset ring-navy-100">
                              {nameInitials(h.changed_by || "—")}
                            </span>
                            <span className="text-sm font-medium text-navy-800">
                              {h.changed_by ? abbreviateName(h.changed_by) : "—"}
                            </span>
                          </div>
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <ConfigDiff config={h.previous_config} />
                        </td>
                        <td className="px-4 py-3 text-sm">
                          <ConfigDiff config={h.new_config} />
                        </td>
                        <td className="whitespace-nowrap px-4 py-3 text-sm">
                          <Badge variant="info" className="font-mono">v{h.appconfig_version}</Badge>
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
