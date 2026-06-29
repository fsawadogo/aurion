/**
 * Status-polling give-up policy (vid-fix-stuck-import).
 *
 * Extracted from VideoImportClient so the rule is unit-testable without
 * rendering the client or faking timers. The video-upload poll previously
 * retried forever on a failing status request (the stuck-spinner bug); it now
 * gives up after this many *consecutive* failures and surfaces a message.
 * A transient 401 is refreshed + retried inside `fetchWithAuth`, so a healthy
 * run resets the count to 0 on the next success.
 */
export const MAX_POLL_ERRORS = 5;

/** True once status requests have failed this many times in a row → stop. */
export function shouldStopPolling(consecutiveErrors: number): boolean {
  return consecutiveErrors >= MAX_POLL_ERRORS;
}
