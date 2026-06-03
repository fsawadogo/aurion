import "@testing-library/jest-dom/vitest";
import { afterEach } from "vitest";
import { cleanup } from "@testing-library/react";

/**
 * Global test setup: extend `expect` with jest-dom matchers and
 * unmount any leftover React trees between tests so component state
 * doesn't bleed across cases.
 */
afterEach(() => {
  cleanup();
});
