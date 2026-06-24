"use client";

/**
 * /portal/admin/prompt-studio — Prompt Studio (create & share, #524).
 *
 * ADMIN surface to author or upload a prompt from scratch, save versions, and
 * publish it to a cohort (self / role / all). Gated behind
 * `feature_flags.prompt_studio_enabled` — when off the API 403s and the page
 * shows a "not enabled" state. The testing / A-B workbench is a later slice.
 */

import { FileText, Plus, Rocket } from "lucide-react";
import {
  ApiError,
  createStudioPrompt,
  getStudioJobs,
  getStudioPrompt,
  humanizeError,
  listStudioPrompts,
  parseDetailError,
  publishStudioPrompt,
  saveStudioVersion,
} from "@/lib/api";
import type {
  StudioJob,
  StudioPromptDetail,
  StudioPromptSummary,
  StudioScope,
} from "@/lib/api";
import { useCallback, useEffect, useState } from "react";
import { useTranslations } from "next-intl";
import Badge from "@/components/ui/Badge";
import Button from "@/components/ui/Button";
import Card from "@/components/ui/Card";
import LoadingSkeleton from "@/components/ui/LoadingSkeleton";
import Modal from "@/components/ui/Modal";
import EmptyPanelState from "@/components/portal/EmptyPanelState";
import PageHeader from "@/components/portal/PageHeader";

const SCOPES: StudioScope[] = ["SELF", "ROLE", "ALL"];
const ROLES = ["CLINICIAN", "EVAL_TEAM", "COMPLIANCE_OFFICER", "ADMIN"];

const INPUT_CLS =
  "w-full rounded-aurion-md border border-hairline bg-white px-3 py-2 text-aurion-callout text-navy-800 placeholder:text-navy-300 focus:outline-none focus:ring-2 focus:ring-gold-300/40";

export default function PromptStudioPage() {
  const t = useTranslations("AdminPromptStudio");
  const [jobs, setJobs] = useState<StudioJob[]>([]);
  const [prompts, setPrompts] = useState<StudioPromptSummary[]>([]);
  const [selected, setSelected] = useState<StudioPromptDetail | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [disabled, setDisabled] = useState(false);
  const [createOpen, setCreateOpen] = useState(false);

  const load = useCallback(async () => {
    setLoading(true);
    setError(null);
    setDisabled(false);
    try {
      const [js, ps] = await Promise.all([getStudioJobs(), listStudioPrompts()]);
      setJobs(js);
      setPrompts(ps);
    } catch (e) {
      // The studio gate raises 403 for two reasons: prompt_studio_enabled is
      // off, or the role isn't in prompt_studio_roles. Under the default config
      // (flag dark, allowlist [ADMIN], nav ADMIN-only) the only 403 an admin
      // hits is flag-off, so both render the "enable it in Feature Flags" state.
      // Distinguishing them for a widened allowlist needs a machine-readable
      // gate error code — deferred follow-up.
      if (e instanceof ApiError && e.status === 403) {
        setDisabled(true);
      } else {
        setError(humanizeError(e, t("loadError")));
      }
    } finally {
      setLoading(false);
    }
  }, [t]);

  useEffect(() => {
    void load();
  }, [load]);

  const openPrompt = useCallback(
    async (id: string) => {
      setError(null);
      try {
        setSelected(await getStudioPrompt(id));
      } catch (e) {
        setError(humanizeError(e, t("loadError")));
      }
    },
    [t],
  );

  async function onCreated(detail: StudioPromptDetail) {
    setCreateOpen(false);
    await load();
    setSelected(detail);
  }

  return (
    <div className="aurion-page-padded" data-testid="prompt-studio-page">
      <PageHeader
        eyebrow={t("eyebrow")}
        title={t("title")}
        description={t("description")}
        actions={
          disabled ? undefined : (
            <Button
              onClick={() => setCreateOpen(true)}
              data-testid="create-prompt-button"
            >
              <Plus className="h-4 w-4 mr-1.5" aria-hidden="true" />
              {t("createButton")}
            </Button>
          )
        }
      />

      {error && (
        <div
          className="mb-4 rounded-aurion-md border border-red-200 bg-red-50 px-4 py-3 text-aurion-callout text-red-700"
          role="alert"
          data-testid="prompt-studio-error"
        >
          {error}
        </div>
      )}

      {disabled ? (
        <Card>
          <div data-testid="prompt-studio-disabled">
            <EmptyPanelState
              icon={<Rocket className="h-5 w-5" aria-hidden="true" />}
              title={t("notEnabledTitle")}
              hint={t("notEnabledBody")}
            />
          </div>
        </Card>
      ) : loading ? (
        <Card>
          <LoadingSkeleton lines={6} />
        </Card>
      ) : (
        <div className="grid gap-5 lg:grid-cols-[1fr_1.4fr]">
          <section aria-label={t("libraryLabel")}>
            {prompts.length === 0 ? (
              <Card>
                <div className="py-10 text-center" data-testid="prompt-studio-empty">
                  <FileText className="mx-auto h-9 w-9 text-gold-300 mb-2" aria-hidden="true" />
                  <p className="aurion-callout text-navy-500">{t("empty")}</p>
                </div>
              </Card>
            ) : (
              <ul className="space-y-2" data-testid="prompt-list">
                {prompts.map((p) => (
                  <li key={p.id}>
                    <button
                      type="button"
                      onClick={() => void openPrompt(p.id)}
                      data-testid={`prompt-row-${p.id}`}
                      className={
                        "w-full rounded-aurion-md border bg-white px-3 py-2.5 text-left transition-colors " +
                        (selected?.id === p.id
                          ? "border-gold-300 ring-1 ring-gold-300/40"
                          : "border-hairline hover:border-navy-200")
                      }
                    >
                      <div className="flex items-center gap-2">
                        <span className="aurion-callout font-medium text-navy-800">
                          {p.name}
                        </span>
                        <Badge variant="neutral">v{p.latest_version_no}</Badge>
                      </div>
                      <code className="text-[11px] font-mono text-navy-400">{p.job_id}</code>
                    </button>
                  </li>
                ))}
              </ul>
            )}
          </section>

          <section aria-label={t("detailLabel")}>
            {selected ? (
              <PromptDetail
                key={selected.id}
                detail={selected}
                onChanged={(d) => setSelected(d)}
              />
            ) : (
              <Card>
                <p className="py-10 text-center aurion-callout text-navy-400">
                  {t("selectHint")}
                </p>
              </Card>
            )}
          </section>
        </div>
      )}

      <CreatePromptModal
        isOpen={createOpen}
        onClose={() => setCreateOpen(false)}
        jobs={jobs}
        onCreated={onCreated}
      />
    </div>
  );
}

function CreatePromptModal({
  isOpen,
  onClose,
  jobs,
  onCreated,
}: {
  isOpen: boolean;
  onClose: () => void;
  jobs: StudioJob[];
  onCreated: (d: StudioPromptDetail) => void | Promise<void>;
}) {
  const t = useTranslations("AdminPromptStudio");
  const [name, setName] = useState("");
  const [jobId, setJobId] = useState("");
  const [text, setText] = useState("");
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);

  function pickJob(id: string) {
    setJobId(id);
    // "Start from current": seed the editor with the job's live default text,
    // unless the author already typed something.
    const job = jobs.find((j) => j.job_id === id);
    if (job && !text.trim()) setText(job.system_prompt);
  }

  async function submit() {
    setSaving(true);
    setError(null);
    try {
      const detail = await createStudioPrompt({
        job_id: jobId,
        name: name.trim(),
        text,
      });
      setName("");
      setJobId("");
      setText("");
      await onCreated(detail);
    } catch (e) {
      setError(parseDetailError(e, t("saveError")));
    } finally {
      setSaving(false);
    }
  }

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={t("createModal.title")}
      size="lg"
      footer={
        <div className="flex justify-end gap-2">
          <Button variant="ghost" onClick={onClose} disabled={saving}>
            {t("cancel")}
          </Button>
          <Button
            onClick={() => void submit()}
            loading={saving}
            disabled={saving || !name.trim() || !jobId || !text.trim()}
            data-testid="create-submit"
          >
            {t("createModal.submit")}
          </Button>
        </div>
      }
    >
      <div className="space-y-3">
        <div>
          <label className="aurion-micro text-gold-600 mb-1 block">
            {t("createModal.nameLabel")}
          </label>
          <input
            value={name}
            onChange={(e) => setName(e.target.value)}
            placeholder={t("createModal.namePlaceholder")}
            className={INPUT_CLS}
            data-testid="create-name-input"
          />
        </div>
        <div>
          <label className="aurion-micro text-gold-600 mb-1 block">
            {t("createModal.jobLabel")}
          </label>
          <select
            value={jobId}
            onChange={(e) => pickJob(e.target.value)}
            className={INPUT_CLS}
            data-testid="create-job-select"
          >
            <option value="">{t("createModal.jobPlaceholder")}</option>
            {jobs.map((j) => (
              <option key={j.job_id} value={j.job_id}>
                {j.name}
              </option>
            ))}
          </select>
        </div>
        <div>
          <label className="aurion-micro text-gold-600 mb-1 block">
            {t("createModal.textLabel")}
          </label>
          <textarea
            value={text}
            onChange={(e) => setText(e.target.value)}
            rows={8}
            placeholder={t("createModal.textPlaceholder")}
            className={INPUT_CLS + " font-mono leading-relaxed"}
            data-testid="create-text-input"
          />
          <p className="mt-1 text-aurion-caption text-navy-400">
            {t("createModal.safetyHint")}
          </p>
        </div>
        {error && (
          <p role="alert" className="text-aurion-caption text-red-700" data-testid="create-error">
            {error}
          </p>
        )}
      </div>
    </Modal>
  );
}

function PromptDetail({
  detail,
  onChanged,
}: {
  detail: StudioPromptDetail;
  onChanged: (d: StudioPromptDetail) => void;
}) {
  const t = useTranslations("AdminPromptStudio");
  const [draft, setDraft] = useState("");
  const [savingVersion, setSavingVersion] = useState(false);
  const [scope, setScope] = useState<StudioScope>("ALL");
  const [role, setRole] = useState("CLINICIAN");
  const [publishing, setPublishing] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [notice, setNotice] = useState<string | null>(null);

  // Backend always creates v1 with the prompt, so versions is non-empty in
  // practice; guard anyway so a malformed payload can't crash the panel.
  const latest = detail.versions[detail.versions.length - 1];
  if (!latest) return null;

  async function saveVersion() {
    setSavingVersion(true);
    setError(null);
    setNotice(null);
    try {
      await saveStudioVersion(detail.id, draft);
      setDraft("");
      const fresh = await getStudioPrompt(detail.id);
      onChanged(fresh);
      setNotice(t("versionSaved", { n: fresh.versions.length }));
    } catch (e) {
      setError(parseDetailError(e, t("saveError")));
    } finally {
      setSavingVersion(false);
    }
  }

  async function publish() {
    setPublishing(true);
    setError(null);
    setNotice(null);
    try {
      const pub = await publishStudioPrompt(detail.id, {
        version_id: latest.id,
        scope,
        ...(scope === "ROLE" ? { target_role: role } : {}),
      });
      setNotice(t("publishedNotice", { scope: pub.scope, v: pub.version_no }));
    } catch (e) {
      setError(parseDetailError(e, t("publishError")));
    } finally {
      setPublishing(false);
    }
  }

  return (
    <Card>
      <div className="flex items-center gap-2">
        <h2 className="aurion-headline text-navy-800">{detail.name}</h2>
        <code className="rounded bg-gray-100 px-1.5 py-0.5 font-mono text-[11px] text-gray-500">
          {detail.job_id}
        </code>
        <Badge variant="neutral">v{latest.version_no}</Badge>
      </div>

      <div className="mt-3">
        <p className="aurion-micro text-gold-600 mb-1">{t("currentVersionLabel")}</p>
        <pre className="max-h-48 overflow-auto rounded-aurion-md border border-hairline bg-gray-50 px-3 py-2 text-aurion-caption leading-relaxed text-navy-700 whitespace-pre-wrap font-mono">
          {latest.text}
        </pre>
      </div>

      <div className="mt-4">
        <p className="aurion-micro text-gold-600 mb-1">{t("newVersionLabel")}</p>
        <textarea
          value={draft}
          onChange={(e) => setDraft(e.target.value)}
          rows={5}
          placeholder={t("newVersionPlaceholder")}
          className={INPUT_CLS + " font-mono leading-relaxed"}
          data-testid="new-version-input"
        />
        <div className="mt-2">
          <Button
            size="sm"
            variant="secondary"
            onClick={() => void saveVersion()}
            loading={savingVersion}
            disabled={savingVersion || !draft.trim()}
            data-testid="save-version-button"
          >
            {t("saveVersion")}
          </Button>
        </div>
      </div>

      <div className="mt-5 border-t border-hairline pt-4">
        <p className="aurion-micro text-gold-600 mb-2 flex items-center gap-1.5">
          <Rocket className="h-3.5 w-3.5" aria-hidden="true" />
          {t("publishLabel", { n: latest.version_no })}
        </p>
        <div className="flex flex-wrap items-center gap-2">
          <select
            value={scope}
            onChange={(e) => setScope(e.target.value as StudioScope)}
            className={INPUT_CLS + " w-auto"}
            data-testid="publish-scope-select"
            aria-label={t("scopeLabel")}
          >
            {SCOPES.map((s) => (
              <option key={s} value={s}>
                {t(`scope.${s}`)}
              </option>
            ))}
          </select>
          {scope === "ROLE" && (
            <select
              value={role}
              onChange={(e) => setRole(e.target.value)}
              className={INPUT_CLS + " w-auto"}
              data-testid="publish-role-select"
              aria-label={t("roleLabel")}
            >
              {ROLES.map((r) => (
                <option key={r} value={r}>
                  {r}
                </option>
              ))}
            </select>
          )}
          <Button
            onClick={() => void publish()}
            loading={publishing}
            disabled={publishing}
            data-testid="publish-button"
          >
            {t("publish")}
          </Button>
        </div>
      </div>

      {notice && (
        <p className="mt-3 text-aurion-caption text-emerald-700" data-testid="detail-notice">
          {notice}
        </p>
      )}
      {error && (
        <p role="alert" className="mt-3 text-aurion-caption text-red-700" data-testid="detail-error">
          {error}
        </p>
      )}
    </Card>
  );
}
