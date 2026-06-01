/**
 * Macro expansion helper for note-edit textareas.
 *
 * Behaviour: when the user types a recognised shortcut followed by a
 * trigger character (space, period, newline, comma), replace the
 * shortcut token with the macro body and place the caret immediately
 * after the inserted text.
 *
 * Lookup is exact-match against the shortcut string (which always
 * starts with `/`). Specialty scoping is applied at the caller level
 * — the consumer hook narrows the macro list to the current note's
 * specialty plus null-scoped macros, then passes the filtered list
 * to `tryExpand`.
 */

import type { PhysicianMacro } from "@/types";

interface ExpansionResult {
  /** New textarea value after the substitution. */
  text: string;
  /** Position where the caret should land. */
  caret: number;
  /** The macro that fired — useful for analytics / undo hooks. */
  macro: PhysicianMacro;
}

const TRIGGER_CHARS = new Set([" ", ".", ",", "\n", ";", "?", "!"]);

/**
 * Try to expand at the current caret position. Returns null when no
 * shortcut matches (caller leaves the textarea alone), or an
 * `ExpansionResult` when a match fires.
 *
 * `text` is the full textarea value; `caret` is the cursor offset
 * (typically `event.target.selectionStart` after the key was typed).
 * `macros` is the candidate list — caller filters by specialty first.
 *
 * Important: this fires AFTER the trigger character has been typed,
 * so `text[caret-1]` is the trigger and the shortcut sits at
 * `text[caret-1-len(shortcut) .. caret-1]`. We preserve the trigger
 * character so the user doesn't lose the natural punctuation flow.
 */
export function tryExpand(
  text: string,
  caret: number,
  macros: PhysicianMacro[],
): ExpansionResult | null {
  if (caret === 0) return null;
  const triggerChar = text[caret - 1];
  if (!TRIGGER_CHARS.has(triggerChar)) return null;

  // Scan backwards from the trigger to find the start of the token
  // (whitespace / start-of-string / line break).
  let start = caret - 1;
  while (start > 0 && !TRIGGER_CHARS.has(text[start - 1])) {
    start -= 1;
  }
  const token = text.slice(start, caret - 1);
  if (!token.startsWith("/") || token.length < 2) return null;

  // Exact match against the candidate macros — longest shortcut wins
  // if multiple match (shouldn't happen with the (owner, shortcut)
  // unique constraint, but defensive).
  const match = macros
    .filter((m) => m.shortcut === token)
    .sort((a, b) => b.shortcut.length - a.shortcut.length)[0];
  if (!match) return null;

  // Replace the token (NOT the trigger) so the punctuation stays.
  const before = text.slice(0, start);
  const trigger = text.slice(caret - 1, caret);
  const after = text.slice(caret);
  const expansion = match.body;
  const newText = before + expansion + trigger + after;
  const newCaret = before.length + expansion.length + trigger.length;

  return { text: newText, caret: newCaret, macro: match };
}

/** Narrow a macro list to those that apply to the given specialty.
 *  Null-specialty macros always pass through; specialty-scoped
 *  macros only when their scope matches. */
export function filterForSpecialty(
  macros: PhysicianMacro[],
  specialty: string,
): PhysicianMacro[] {
  return macros.filter((m) => !m.specialty || m.specialty === specialty);
}
