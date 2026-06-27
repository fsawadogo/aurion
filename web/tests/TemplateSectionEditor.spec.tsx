import { describe, expect, it } from "vitest";
import { useState } from "react";
import { render, screen, fireEvent } from "@testing-library/react";

import TemplateSectionEditor, {
  blankTemplate,
  normalizeTemplate,
  slugify,
  validateTemplate,
} from "@/components/portal/TemplateSectionEditor";
import { withIntl } from "./helpers/intl";
import type { TemplateDefinition } from "@/types";

const good: TemplateDefinition = {
  key: "ortho_custom",
  display_name: "Ortho Custom",
  version: "1.0",
  sections: [
    { id: "hpi", title: "HPI", required: true, visual_trigger_keywords: [], description: "" },
  ],
};

describe("template editor helpers", () => {
  it("slugify produces a snake_case key", () => {
    expect(slugify("Lower-Limb New Patient")).toBe("lower_limb_new_patient");
    expect(slugify("  ACL Repair!! ")).toBe("acl_repair");
  });

  it("validateTemplate accepts a good draft and names the first problem otherwise", () => {
    expect(validateTemplate(good)).toBeNull();
    expect(validateTemplate(blankTemplate())).toBe("errKeyRequired");
    expect(validateTemplate({ ...good, key: "Bad Key" })).toBe("errKeyShape");
    expect(validateTemplate({ ...good, display_name: "" })).toBe("errNameRequired");
    expect(validateTemplate({ ...good, sections: [] })).toBe("errNoSections");
    expect(
      validateTemplate({
        ...good,
        sections: [good.sections[0], { ...good.sections[0] }],
      }),
    ).toBe("errDuplicateId");
    expect(
      validateTemplate({
        ...good,
        sections: [{ ...good.sections[0], title: "" }],
      }),
    ).toBe("errSectionTitle");
    // Keyword caps (create path).
    expect(
      validateTemplate({
        ...good,
        sections: [
          { ...good.sections[0], visual_trigger_keywords: Array(51).fill("k") },
        ],
      }),
    ).toBe("errTooManyKeywords");
    expect(
      validateTemplate({
        ...good,
        sections: [{ ...good.sections[0], visual_trigger_keywords: ["x".repeat(51)] }],
      }),
    ).toBe("errKeywordLong");
  });

  it("relaxes section caps on the update path (enforceSectionCaps:false)", () => {
    // A 600-char description + 60 sections fail on create but pass on update,
    // mirroring the backend's update-time relaxation — so editing a pre-cap
    // template isn't blocked.
    const overCap: TemplateDefinition = {
      key: "ortho_custom",
      display_name: "Ortho Custom",
      version: "1.0",
      sections: Array.from({ length: 60 }, (_, i) => ({
        id: `s${i}`,
        title: "T",
        required: true,
        visual_trigger_keywords: [],
        description: "x".repeat(600),
      })),
    };
    expect(validateTemplate(overCap)).toBe("errTooManySections");
    expect(validateTemplate(overCap, { enforceSectionCaps: false })).toBeNull();
    // Always-on rules still apply on update (empty title rejected).
    expect(
      validateTemplate(
        { ...overCap, sections: [{ ...overCap.sections[0], title: "" }] },
        { enforceSectionCaps: false },
      ),
    ).toBe("errSectionTitle");
  });

  it("normalizeTemplate trims fields and strips empty keywords", () => {
    const messy: TemplateDefinition = {
      key: " k ",
      display_name: " Name ",
      version: "",
      sections: [
        {
          id: " s ",
          title: " T ",
          required: true,
          visual_trigger_keywords: ["a", "", " b "],
          description: "",
        },
      ],
    };
    const n = normalizeTemplate(messy);
    expect(n.key).toBe("k");
    expect(n.display_name).toBe("Name");
    expect(n.version).toBe("1.0"); // empty version defaults
    expect(n.sections[0].id).toBe("s");
    expect(n.sections[0].visual_trigger_keywords).toEqual(["a", "b"]);
  });

  it("blankTemplate seeds system_prompt; normalizeTemplate trims it / nulls when blank", () => {
    expect(blankTemplate().system_prompt).toBe("");
    expect(
      normalizeTemplate({ ...good, system_prompt: "  Describe only.  " }).system_prompt,
    ).toBe("Describe only.");
    expect(
      normalizeTemplate({ ...good, system_prompt: "   " }).system_prompt,
    ).toBeNull();
    expect(normalizeTemplate(good).system_prompt).toBeNull();
  });
});

function Harness({ initial }: { initial?: TemplateDefinition }) {
  const [v, setV] = useState<TemplateDefinition>(initial ?? blankTemplate());
  return <TemplateSectionEditor value={v} onChange={setV} />;
}

describe("TemplateSectionEditor", () => {
  it("adds, edits, and removes sections", () => {
    render(withIntl(<Harness />));

    // Starts with one section.
    expect(screen.getByTestId("section-row-0")).toBeTruthy();
    expect(screen.queryByTestId("section-row-1")).toBeNull();

    // Add a section.
    fireEvent.click(screen.getByText("Add section"));
    expect(screen.getByTestId("section-row-1")).toBeTruthy();

    // Edit the first section's title.
    const title0 = screen.getByTestId("section-title-0") as HTMLInputElement;
    fireEvent.change(title0, { target: { value: "History" } });
    expect((screen.getByTestId("section-title-0") as HTMLInputElement).value).toBe(
      "History",
    );

    // Remove the second section → back to one.
    fireEvent.click(screen.getByTestId("section-remove-1"));
    expect(screen.queryByTestId("section-row-1")).toBeNull();
  });

  it("edits the AI instructions field", () => {
    render(withIntl(<Harness />));
    const ta = screen.getByTestId("template-system-prompt") as HTMLTextAreaElement;
    expect(ta.value).toBe("");
    fireEvent.change(ta, { target: { value: "Describe only what was observed." } });
    expect(
      (screen.getByTestId("template-system-prompt") as HTMLTextAreaElement).value,
    ).toBe("Describe only what was observed.");
  });
});
