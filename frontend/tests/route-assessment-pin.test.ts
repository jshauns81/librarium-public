// @vitest-environment jsdom
import { afterEach, expect, it } from "vitest";
import { parameters } from "../src/App";

afterEach(() => history.replaceState(null, "", "/"));

const fa = (query: string) => {
  history.replaceState(null, "", `/?view=files&${query}`);
  return parameters().fa;
};

it("keeps the assessment an older link pinned for a review copy or delivery", () => {
  expect(fa("fa=one&faj=two")).toBe("two");
  expect(fa("fa=one&fda=three")).toBe("three");
  expect(fa("faj=two&fda=three")).toBe("two");
  expect(fa("fa=one")).toBe("one");
  expect(fa("fg=four")).toBe("");
});

it("still refuses a repeated assessment pin", () => {
  expect(fa("faj=two&faj=five")).toBe("invalid-duplicate-selection");
});
