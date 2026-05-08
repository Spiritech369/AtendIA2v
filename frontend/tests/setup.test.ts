/**
 * Smoke test — verifies vitest + jsdom + jest-dom matchers all wire up.
 * Will be deleted once real tests land in T10+.
 */
import { describe, expect, it } from "vitest";

describe("test infra", () => {
  it("can run a vitest test", () => {
    expect(1 + 1).toBe(2);
  });

  it("has jsdom DOM globals", () => {
    const div = document.createElement("div");
    div.textContent = "hello";
    expect(div.textContent).toBe("hello");
  });
});
