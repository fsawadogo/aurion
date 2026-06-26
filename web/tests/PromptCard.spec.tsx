import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";
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
};

const PUBLICATION = {
  name: "Tighter PE",
  version_no: 2,
  scope: "ALL" as const,
  target_role: null,
  published_at: "2026-06-24T00:00:00Z",
};

describe("PromptCard — admin publication banner", () => {
  it("renders no banner when no publication applies", () => {
    render(withIntl(<PromptCard prompt={BASE} />));
    expect(
      screen.queryByTestId("prompt-card-note_generation-publication"),
    ).not.toBeInTheDocument();
  });

  it("shows the active banner when a publication applies and there's no override", () => {
    render(
      withIntl(
        <PromptCard prompt={{ ...BASE, admin_publication: PUBLICATION }} />,
      ),
    );
    const banner = screen.getByTestId(
      "prompt-card-note_generation-publication",
    );
    expect(banner).toBeInTheDocument();
    expect(banner.textContent).toContain("Tighter PE");
    expect(banner.textContent).toContain("your notes currently use");
  });

  it("shows the shadowed banner when the clinician also has an override", () => {
    render(
      withIntl(
        <PromptCard
          prompt={{
            ...BASE,
            is_overridden: true,
            user_prompt_text: "MY OWN PROMPT",
            active_prompt: "MY OWN PROMPT",
            admin_publication: PUBLICATION,
          }}
        />,
      ),
    );
    const banner = screen.getByTestId(
      "prompt-card-note_generation-publication",
    );
    expect(banner.textContent).toContain("takes priority");
  });
});
