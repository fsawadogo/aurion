import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor, fireEvent } from "@testing-library/react";
import { withIntl } from "./helpers/intl";
import NoteAssistChat from "@/components/portal/NoteAssistChat";

// humanizeError passthrough — the component uses it for the error bubble.
vi.mock("@/lib/api", () => ({ humanizeError: (_e: unknown, fb: string) => fb }));

const PLACEHOLDER = "Ask, edit, or fix anything…";

describe("NoteAssistChat (fix this note)", () => {
  beforeEach(() => vi.clearAllMocks());

  it("sends the typed message and shows both the user and assistant bubbles", async () => {
    const onAssist = vi.fn().mockResolvedValue({
      assistant_message: "Shortened the HPI.",
      applied: true,
      note: {},
    });
    render(withIntl(<NoteAssistChat onAssist={onAssist} />));

    fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER), {
      target: { value: "shorten the hpi" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    await waitFor(() =>
      expect(onAssist).toHaveBeenCalledWith("shorten the hpi"),
    );
    expect(await screen.findByText("Shortened the HPI.")).toBeTruthy();
    expect(screen.getByText("shorten the hpi")).toBeTruthy(); // user bubble
  });

  it("surfaces the error IN the chat, not a page banner", async () => {
    const onAssist = vi.fn().mockRejectedValue(new Error("boom"));
    render(withIntl(<NoteAssistChat onAssist={onAssist} />));

    fireEvent.change(screen.getByPlaceholderText(PLACEHOLDER), {
      target: { value: "do it" },
    });
    fireEvent.click(screen.getByRole("button", { name: "Send" }));

    expect(
      await screen.findByText("Couldn't apply that. Please try again."),
    ).toBeTruthy();
  });

  it("a quick chip sends its label as the message", async () => {
    const onAssist = vi.fn().mockResolvedValue({
      assistant_message: "ok",
      applied: false,
      note: {},
    });
    render(withIntl(<NoteAssistChat onAssist={onAssist} />));

    fireEvent.click(screen.getByRole("button", { name: "Shorten the note" }));

    await waitFor(() =>
      expect(onAssist).toHaveBeenCalledWith("Shorten the note"),
    );
  });

  it("enables send only with input, and clears the input after a send", async () => {
    const onAssist = vi
      .fn()
      .mockResolvedValue({ assistant_message: "ok", applied: false, note: {} });
    render(withIntl(<NoteAssistChat onAssist={onAssist} />));
    const send = screen.getByRole("button", { name: "Send" }) as HTMLButtonElement;
    const input = screen.getByPlaceholderText(PLACEHOLDER) as HTMLInputElement;

    expect(send.disabled).toBe(true); // no input
    fireEvent.change(input, { target: { value: "shorten" } });
    expect(send.disabled).toBe(false); // re-enables with input

    fireEvent.click(send);
    await waitFor(() => expect(onAssist).toHaveBeenCalledWith("shorten"));
    await waitFor(() => expect(input.value).toBe("")); // cleared after send
  });
});
