"use client";

import { Check } from "lucide-react";
import { useTranslations } from "next-intl";
import { updateMyProfile } from "@/lib/portal-api";
import {
  ACCENT_KEYS,
  ACCENT_SWATCH,
  applyAccent,
  type AccentKey,
} from "@/lib/accent";

/**
 * #418 accent-color picker — five curated swatches a clinician picks to
 * brand the portal chrome.
 *
 * Mirrors ThemeToggle's model: flip the live DOM immediately
 * (`applyAccent`), then best-effort persist to the profile
 * (PUT /profile). The local flip already happened, so a failed persist
 * is silent — the Sidebar re-applies the stored value on next load.
 *
 * Compliance surfaces (CONFLICTS amber, masking, audit navy) are
 * separate tokens and are NOT affected by this control.
 *
 * Controlled: the active swatch is driven entirely by the `value` prop.
 * The parent (profile page) reflects each pick back through `onChange`,
 * so the highlight tracks the page's draft — including a Cancel/discard
 * that resets it.
 */
interface AccentPickerProps {
  value: AccentKey;
  /** Bubble the persisted choice up so the parent page's profile/draft
   *  state stays in sync with what's now on the server + the DOM. */
  onChange?: (next: AccentKey) => void;
}

export default function AccentPicker({ value, onChange }: AccentPickerProps) {
  const t = useTranslations("Profile.accent");

  const handlePick = async (next: AccentKey) => {
    if (next === value) return;
    // 1. Live preview — swap the DOM scale instantly.
    applyAccent(next);
    onChange?.(next);
    // 2. Best-effort persist; silent on failure.
    try {
      await updateMyProfile({ accent_color: next });
    } catch {
      // No surfaced error at this layer — the live flip already applied.
    }
  };

  return (
    <div
      role="radiogroup"
      aria-label={t("label")}
      className="flex flex-wrap gap-3"
    >
      {ACCENT_KEYS.map((key) => {
        const isActive = value === key;
        return (
          <button
            key={key}
            type="button"
            role="radio"
            aria-checked={isActive}
            data-testid={`accent-swatch-${key}`}
            onClick={() => void handlePick(key)}
            title={t(`swatch.${key}`)}
            aria-label={t(`swatch.${key}`)}
            className={
              "relative flex h-10 w-10 items-center justify-center rounded-full " +
              "ring-2 ring-offset-2 ring-offset-surface transition-all duration-short " +
              (isActive
                ? "ring-navy-700 scale-105"
                : "ring-transparent hover:scale-105")
            }
            style={{ backgroundColor: ACCENT_SWATCH[key] }}
          >
            {isActive && (
              <Check className="h-4 w-4 text-white drop-shadow" strokeWidth={3} />
            )}
          </button>
        );
      })}
    </div>
  );
}
