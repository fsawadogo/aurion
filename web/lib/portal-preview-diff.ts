/**
 * Pure diff function for comparing a live preview (#64) snapshot
 * against the canonical Stage 1 note.
 *
 * This is a pilot-evaluation surface: "how close did the preview
 * get?" Used by the eval team and the CTO to tune preview cadence,
 * compare LLM providers, etc. Read-only — no edits flow back.
 *
 * Why a pure function (not a backend endpoint):
 *   - Both endpoints already exist (`getMyLatestSessionPreview` +
 *     `getNoteDetail`); the diff is just a comparison
 *   - No PHI risk that isn't already in the existing endpoints
 *   - Keeps the backend lean — the diff is presentation, not data
 *   - Easier to iterate on the matching heuristic in TypeScript
 *
 * The diff matches preview claims to final claims:
 *   1. Exact source_id match — both anchored to the same transcript
 *      segment / frame / etc. → "matched"
 *   2. Synthetic preview source_ids (`preview_seg_0`, etc.) can't
 *      match; treated as preview-only unless we find a text fuzzy
 *      match (first N chars of normalized text) — labeled "fuzzy"
 *      so the eval team knows it's heuristic
 *   3. Final claim with no preview counterpart → "final_only"
 *      (preview missed it; e.g. the physician finished documenting
 *      after the last preview snapshot fired)
 *   4. Preview claim with no final counterpart → "preview_only"
 *      (LLM took something out of the final — could be self-critique
 *      dropping unanchored claims, or just normal Stage-1 refinement)
 */

import type { Claim, LivePreviewSection, NoteSection } from "@/types";

export type ClaimMatchKind = "matched" | "fuzzy" | "preview_only" | "final_only";

export interface ClaimDiffEntry {
  kind: ClaimMatchKind;
  preview_claim?: {
    id: string;
    text: string;
    source_id: string;
    source_type: string;
  };
  final_claim?: Claim;
}

export interface SectionDiffEntry {
  section_id: string;
  title: string;
  /** Section appears in BOTH; entries are claim-level comparisons. */
  in_preview: boolean;
  in_final: boolean;
  /** Status from the FINAL note (more authoritative). */
  final_status?: string;
  claims: ClaimDiffEntry[];
}

export interface PreviewToFinalDiff {
  /** Section-level entries. Order matches the FINAL note's section
   *  ordering — that's the canonical layout the physician saw.
   *  Preview-only sections (LLM hallucinated one) appear at the end. */
  sections: SectionDiffEntry[];
  /** Top-level counts for the header summary chip. */
  totals: {
    matched: number;
    fuzzy: number;
    preview_only: number;
    final_only: number;
  };
  /** Reflects WHICH preview we diffed against — version + transcript_chars +
   *  created_at, surfaced in the panel header. */
  preview_meta: {
    version: number;
    transcript_chars: number;
    created_at: string;
    provider_used: string;
  };
}

/** Number of leading normalized chars used for fuzzy text matching.
 *  Tuned for the failure mode this is meant to catch: the LLM
 *  rephrasing the same observation slightly between preview and
 *  final. Short enough to tolerate minor edits; long enough to
 *  avoid false matches on common openings like "patient reports". */
const FUZZY_PREFIX_LEN = 40;

/** Source IDs that the preview synthesizes (since real transcript
 *  anchors don't exist mid-recording). Exact match against these is
 *  meaningless — preview emitted them all under the same synthetic
 *  segment. The fuzzy path is the only way to match these to finals. */
const SYNTHETIC_PREVIEW_SOURCE_IDS = new Set(["preview_seg_0"]);

/** Lowercase + collapse whitespace for fuzzy comparison. */
function normalizeText(s: string): string {
  return s.trim().toLowerCase().replace(/\s+/g, " ");
}

function fuzzyKey(text: string): string {
  return normalizeText(text).slice(0, FUZZY_PREFIX_LEN);
}

interface PreviewClaimSummary {
  id: string;
  text: string;
  source_id: string;
  source_type: string;
}

function summarizePreviewClaim(c: {
  id: string;
  text: string;
  source_id: string;
  source_type: string;
}): PreviewClaimSummary {
  return {
    id: c.id,
    text: c.text,
    source_id: c.source_id,
    source_type: c.source_type,
  };
}

/** Match claims within a single section between preview and final.
 *  Returns a flat list of diff entries that preserves the FINAL
 *  ordering (with preview-only entries appended at the end of
 *  the section). */
function diffClaimsInSection(
  preview_claims: Array<{
    id: string;
    text: string;
    source_id: string;
    source_type: string;
  }>,
  final_claims: Claim[],
): ClaimDiffEntry[] {
  // Build lookup structures over the preview claims so the final
  // pass can find counterparts efficiently. We track CONSUMED preview
  // claims separately so the leftover set is preview-only.
  const previewBySourceId = new Map<string, typeof preview_claims[number]>();
  const previewByFuzzy = new Map<string, typeof preview_claims[number]>();
  for (const pc of preview_claims) {
    // Real (non-synthetic) source_ids index exact matches.
    if (!SYNTHETIC_PREVIEW_SOURCE_IDS.has(pc.source_id)) {
      previewBySourceId.set(pc.source_id, pc);
    }
    // Always index fuzzy — covers the synthetic case + handles
    // the "LLM rephrased it" case for real source_ids too.
    const fk = fuzzyKey(pc.text);
    if (fk && !previewByFuzzy.has(fk)) {
      previewByFuzzy.set(fk, pc);
    }
  }

  const consumed = new Set<string>();
  const out: ClaimDiffEntry[] = [];

  for (const fc of final_claims) {
    // 1. Exact match by source_id — both anchored to the same
    //    underlying source.
    const exact = previewBySourceId.get(fc.source_id);
    if (exact && !consumed.has(exact.id)) {
      consumed.add(exact.id);
      out.push({
        kind: "matched",
        preview_claim: summarizePreviewClaim(exact),
        final_claim: fc,
      });
      continue;
    }
    // 2. Fuzzy text prefix match — handles the synthetic-source-id
    //    case and the LLM-rephrase case.
    const fuzzy = previewByFuzzy.get(fuzzyKey(fc.text));
    if (fuzzy && !consumed.has(fuzzy.id)) {
      consumed.add(fuzzy.id);
      out.push({
        kind: "fuzzy",
        preview_claim: summarizePreviewClaim(fuzzy),
        final_claim: fc,
      });
      continue;
    }
    // 3. Final-only — preview didn't have it.
    out.push({ kind: "final_only", final_claim: fc });
  }

  // 4. Remaining preview claims that weren't consumed → preview-only.
  for (const pc of preview_claims) {
    if (consumed.has(pc.id)) continue;
    out.push({ kind: "preview_only", preview_claim: summarizePreviewClaim(pc) });
  }

  return out;
}

/** Build the section-level diff: walk final's sections (canonical
 *  ordering), then append preview-only sections at the end. */
export function diffPreviewVsFinal(
  preview: {
    version: number;
    transcript_chars: number;
    created_at: string;
    provider_used: string;
    sections: LivePreviewSection[];
  },
  final_sections: NoteSection[],
): PreviewToFinalDiff {
  const finalById = new Map<string, NoteSection>();
  for (const s of final_sections) finalById.set(s.id, s);

  const previewById = new Map<string, LivePreviewSection>();
  for (const s of preview.sections) previewById.set(s.id, s);

  const sectionEntries: SectionDiffEntry[] = [];

  // Walk final ordering first (canonical layout).
  for (const fs of final_sections) {
    const ps = previewById.get(fs.id);
    const previewClaims = (ps?.claims ?? []).map((c) => ({
      id: c.id,
      text: c.text,
      source_id: c.source_id,
      source_type: c.source_type,
    }));
    sectionEntries.push({
      section_id: fs.id,
      title: fs.title || fs.id.replace(/_/g, " "),
      in_preview: !!ps,
      in_final: true,
      final_status: fs.status,
      claims: diffClaimsInSection(previewClaims, fs.claims),
    });
  }

  // Then preview-only sections (LLM hallucinated a section the final
  // doesn't have — usually noise, occasionally a self-critique drop).
  for (const ps of preview.sections) {
    const id = ps.id;
    if (finalById.has(id)) continue;
    const previewClaims = (ps.claims ?? []).map((c) => ({
      id: c.id,
      text: c.text,
      source_id: c.source_id,
      source_type: c.source_type,
    }));
    sectionEntries.push({
      section_id: id,
      title: ps.title || id.replace(/_/g, " "),
      in_preview: true,
      in_final: false,
      claims: diffClaimsInSection(previewClaims, []),
    });
  }

  // Tally up across all sections.
  const totals = { matched: 0, fuzzy: 0, preview_only: 0, final_only: 0 };
  for (const s of sectionEntries) {
    for (const c of s.claims) totals[c.kind] += 1;
  }

  return {
    sections: sectionEntries,
    totals,
    preview_meta: {
      version: preview.version,
      transcript_chars: preview.transcript_chars,
      created_at: preview.created_at,
      provider_used: preview.provider_used,
    },
  };
}

/** Headline percentage: of the FINAL note's claims, what fraction
 *  the preview already had (exact or fuzzy match). Useful as a
 *  single-number summary in the panel header. Returns null when
 *  the final has no claims (avoids divide-by-zero in the chip). */
export function previewRecallPercent(diff: PreviewToFinalDiff): number | null {
  const finalCount = diff.totals.matched + diff.totals.fuzzy + diff.totals.final_only;
  if (finalCount === 0) return null;
  return Math.round(
    ((diff.totals.matched + diff.totals.fuzzy) * 100) / finalCount,
  );
}
