import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import PromptCard from "@/components/portal/PromptCard";
import { withIntl } from "./helpers/intl";
import type { AIPrompt } from "@/types";

const BASE: AIPrompt = {
  id: "note_generation",
  name: "Note generation",
  purpose: "Drafts the clinical note from the transcript.",
  category: "note",
  runs_when: "After the visit ends",
  provider_field: "note_generation",
  system_prompt: "SYSTEM PROMPT",
  system_prompt_is_fallback: true,
  schema_note: null,
  user_prompt_text: null,
  is_overridden: false,
  active_prompt: "SYSTEM PROMPT",
  active_source: "default",
};

const PUBLICATION = {
  name: "Tighter PE",
  version_no: 2,
  scope: "ALL" as const,
  target_role: null,
  published_at: "2026-06-24T00:00:00Z",
};

describe("PromptCard — admin publication source label", () => {
  it("renders no banner when the active prompt is the system default", () => {
    render(withIntl(<PromptCard prompt={BASE} />));
    expect(
      screen.queryByTestId("prompt-card-note_generation-publication"),
    ).not.toBeInTheDocument();
  });

  it("shows 'set by your admin' and the published text when a publication is active", async () => {
    const user = userEvent.setup();
    render(
      withIntl(
        <PromptCard
          prompt={{
            ...BASE,
            active_prompt: "PUBLISHED PROMPT BODY",
            active_source: "published",
            admin_publication: PUBLICATION,
          }}
        />,
      ),
    );
    const banner = screen.getByTestId(
      "prompt-card-note_generation-publication",
    );
    expect(banner.textContent).toContain("Tighter PE");
    expect(banner.textContent).toContain("your notes use");
    // The active prompt shown IS the published text, not the registry default.
    await user.click(screen.getByTestId("prompt-card-note_generation-toggle"));
    expect(
      screen.getByTestId("prompt-card-note_generation-pre").textContent,
    ).toContain("PUBLISHED PROMPT BODY");
  });

  it("flags the publication as shadowed when the clinician has an override", () => {
    render(
      withIntl(
        <PromptCard
          prompt={{
            ...BASE,
            is_overridden: true,
            user_prompt_text: "MY OWN PROMPT",
            active_prompt: "MY OWN PROMPT",
            active_source: "override",
            admin_publication: PUBLICATION,
          }}
        />,
      ),
    );
    const banner = screen.getByTestId(
      "prompt-card-note_generation-publication",
    );
    expect(banner.textContent).toContain("also published");
  });
});
