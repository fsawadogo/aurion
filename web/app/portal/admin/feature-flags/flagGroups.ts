import type { FeatureFlags } from "@/types";

/**
 * The flags the Feature Flags page mutates, grouped by where they take
 * effect. Each group renders as its own card with a heading + hint; order =
 * display order. The `titleKey`/`hintKey` resolve under the `FeatureFlags`
 * i18n namespace.
 *
 * **This is an ALLOWLIST, not an incomplete rendering of FeatureFlagsConfig.**
 * Every other flag in the block — screen capture, note versioning, the
 * video-vision gates, `prompt_studio_roles` — is deliberately read-only here
 * because it gates deeper pipeline behaviour or isn't a simple boolean.
 * Making this page generic over the config would surface pipeline gates as
 * innocuous switches and render the roles list as a broken toggle.
 *
 * Lives in its own module rather than in `page.tsx` because Next.js forbids
 * extra named exports from a page file (the build fails with an
 * `OmitWithTag` type error), and the drift-guard test must import the REAL
 * list — a test carrying its own copy would track nothing.
 */
export const FLAG_GROUPS = [
  {
    titleKey: "sectionCards",
    hintKey: "sectionCardsHint",
    flags: [
      "orders_card_enabled",
      "coding_card_enabled",
      "patient_summary_card_enabled",
      "emr_writeback_card_enabled",
    ],
  },
  {
    titleKey: "aiPrompts",
    hintKey: "aiPromptsHint",
    flags: ["prompt_studio_enabled", "clinician_prompts_note_only"],
  },
  {
    titleKey: "groundedSynthesis",
    hintKey: "groundedSynthesisHint",
    flags: ["grounded_synthesis_enabled"],
  },
  {
    titleKey: "templateEngine",
    hintKey: "templateEngineHint",
    flags: ["template_engine_enabled"],
  },
  {
    titleKey: "groundedVisualFindings",
    hintKey: "groundedVisualFindingsHint",
    flags: ["grounded_visual_findings_enabled"],
  },
  {
    titleKey: "parallelFusion",
    hintKey: "parallelFusionHint",
    flags: ["parallel_fusion_enabled"],
  },
  {
    titleKey: "correctionMemory",
    hintKey: "correctionMemoryHint",
    flags: ["correction_memory_enabled", "correction_rules_in_prompt_enabled"],
  },
  {
    titleKey: "videoImport",
    hintKey: "videoImportHint",
    flags: ["multi_clip_import_enabled"],
  },
  {
    titleKey: "noteOptions",
    hintKey: "noteOptionsHint",
    flags: ["note_options_enabled"],
  },
  {
    titleKey: "chatTools",
    hintKey: "chatToolsHint",
    flags: ["template_authoring_chat_enabled", "note_review_chat_enabled"],
  },
] as const satisfies readonly {
  titleKey: string;
  hintKey: string;
  flags: readonly (keyof FeatureFlags)[];
}[];

export const EDITABLE_FLAGS = FLAG_GROUPS.flatMap((g) => g.flags);

export type EditableFlag = (typeof EDITABLE_FLAGS)[number];
