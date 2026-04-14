/**
 * Frontend utility tests — run with Bun's built-in test runner.
 *
 *   cd lightrag_webui
 *   bun test src/__tests__/utils/formatters.test.ts
 *   bun test          ← runs all *.test.ts files
 *   bun test --watch  ← re-runs on save
 *
 * These tests are pure TypeScript — no DOM, no React — so they run
 * instantly without any framework setup.
 */

import { describe, expect, test } from "bun:test";

// ---------------------------------------------------------------------------
// Helpers under test
// ---------------------------------------------------------------------------
// Import from wherever the actual utility lives in `src/utils/`.
// If you rename the util, update this import path.
//
// Example: import { truncateText, formatBytes } from "../../utils/formatters";
//
// For now we inline the helpers so this file is self-contained and can
// serve as a living example of the testing pattern.
// ---------------------------------------------------------------------------

/** Truncate a string to `max` characters, appending `…` when cut. */
function truncateText(text: string, max: number): string {
  if (text.length <= max) return text;
  return text.slice(0, max) + "…";
}

/** Format a byte count as a human-readable string. */
function formatBytes(bytes: number, decimals = 2): string {
  if (bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return `${parseFloat((bytes / Math.pow(k, i)).toFixed(decimals))} ${sizes[i]}`;
}

/** Capitalise the first character of a string. */
function capitaliseFirst(s: string): string {
  if (!s) return s;
  return s.charAt(0).toUpperCase() + s.slice(1);
}

// ---------------------------------------------------------------------------
// truncateText
// ---------------------------------------------------------------------------

describe("truncateText", () => {
  test("returns full string when within limit", () => {
    expect(truncateText("hello", 10)).toBe("hello");
  });

  test("returns full string when exactly at limit", () => {
    expect(truncateText("hello", 5)).toBe("hello");
  });

  test("truncates and appends ellipsis when over limit", () => {
    expect(truncateText("hello world", 5)).toBe("hello…");
  });

  test("handles empty string", () => {
    expect(truncateText("", 10)).toBe("");
  });

  test("limit of 0 returns just the ellipsis", () => {
    expect(truncateText("abc", 0)).toBe("…");
  });
});

// ---------------------------------------------------------------------------
// formatBytes
// ---------------------------------------------------------------------------

describe("formatBytes", () => {
  test("0 bytes returns '0 B'", () => {
    expect(formatBytes(0)).toBe("0 B");
  });

  test("1024 bytes returns '1 KB'", () => {
    expect(formatBytes(1024)).toBe("1 KB");
  });

  test("1 MB", () => {
    expect(formatBytes(1024 * 1024)).toBe("1 MB");
  });

  test("fractional KB rounded to 2 decimals", () => {
    // 1536 bytes = 1.5 KB
    expect(formatBytes(1536)).toBe("1.5 KB");
  });

  test("respects custom decimal places", () => {
    expect(formatBytes(1536, 0)).toBe("2 KB");
  });
});

// ---------------------------------------------------------------------------
// capitaliseFirst
// ---------------------------------------------------------------------------

describe("capitaliseFirst", () => {
  test("capitalises first letter", () => {
    expect(capitaliseFirst("hello")).toBe("Hello");
  });

  test("already-capitalised string unchanged", () => {
    expect(capitaliseFirst("Hello")).toBe("Hello");
  });

  test("empty string returns empty string", () => {
    expect(capitaliseFirst("")).toBe("");
  });

  test("single character", () => {
    expect(capitaliseFirst("a")).toBe("A");
  });

  test("does not lowercase the rest", () => {
    expect(capitaliseFirst("hELLO")).toBe("HELLO");
  });
});
