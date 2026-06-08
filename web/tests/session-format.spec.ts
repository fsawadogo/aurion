import { describe, expect, it } from "vitest";

import {
  abbreviateName,
  nameInitials,
  shortSessionId,
} from "@/lib/session-format";

describe("shortSessionId", () => {
  it("takes the first 8 hex chars of a UUID", () => {
    expect(shortSessionId("b90baea3-56fb-4a4f-95cd-1c95b15fc9f4")).toBe(
      "b90baea3",
    );
  });
});

describe("abbreviateName", () => {
  it("renders first-initial + surname", () => {
    expect(abbreviateName("Faical Sawadogo")).toBe("F. Sawadogo");
  });

  it("strips a leading honorific (Dr., Dre)", () => {
    expect(abbreviateName("Dr. Perry Gdalevitch")).toBe("P. Gdalevitch");
    expect(abbreviateName("Dre Marie Gdalevitch")).toBe("M. Gdalevitch");
  });

  it("uses the last token as the surname when there are middle names", () => {
    expect(abbreviateName("Anna Maria Rossi")).toBe("A. Rossi");
  });

  it("returns a single token unchanged (no surname to abbreviate)", () => {
    expect(abbreviateName("Madonna")).toBe("Madonna");
    expect(abbreviateName("Admin")).toBe("Admin");
  });

  it("handles empty / whitespace-only input", () => {
    expect(abbreviateName("")).toBe("");
    expect(abbreviateName("   ")).toBe("");
  });
});

describe("nameInitials", () => {
  it("returns first + last initials", () => {
    expect(nameInitials("Faical Sawadogo")).toBe("FS");
  });

  it("strips a leading honorific", () => {
    expect(nameInitials("Dr. Perry Gdalevitch")).toBe("PG");
  });

  it("returns one initial for a single token", () => {
    expect(nameInitials("Admin")).toBe("A");
  });

  it("falls back to an em dash for empty input", () => {
    expect(nameInitials("")).toBe("—");
    expect(nameInitials("—")).toBe("—");
  });
});
