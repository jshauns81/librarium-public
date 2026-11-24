// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  within,
} from "@testing-library/react";
import axe from "axe-core";
import { ContentsPlan } from "../src/ContentsPlan";
import type { EpubContentsPlan, EpubContentsPlanEntry } from "../src/types";

const source = "a".repeat(64);
const inspection = "librarium.epub-structure.v4";
const entry = (
  overrides: Partial<EpubContentsPlanEntry> = {},
): EpubContentsPlanEntry => ({
  label: "Chapter 1",
  path: "EPUB/chapter.xhtml",
  fragment: "one",
  requires_anchor: false,
  origin: "heading",
  position: {
    document_index: 0,
    source_index: 3,
    word_offset: 0,
    document_sha256: "b".repeat(64),
  },
  label_source: {
    path: "EPUB/chapter.xhtml",
    source_index: 3,
    document_sha256: "b".repeat(64),
  },
  children: [],
  ...overrides,
});
const plan = (overrides: Partial<EpubContentsPlan> = {}): EpubContentsPlan => ({
  policy_version: "librarium.contents-plan.v1",
  source_sha256: source,
  inspection_policy: inspection,
  decision: "keep",
  reason_codes: ["existing_navigation_sound"],
  existing: [
    {
      label: "Existing opening",
      path: "EPUB/chapter.xhtml",
      fragment: "one",
      kind: "nav",
      ancestors: [],
    },
  ],
  entries: [],
  excluded_targets: [],
  limitations: ["EPUBCheck was not run."],
  ready: false,
  ...overrides,
});

function show(value?: EpubContentsPlan | null) {
  return render(
    <main>
      <h1>Inspection</h1>
      <h2>Structural result</h2>
      <h3>Full report</h3>
      <ContentsPlan
        plan={value}
        sourceSha256={source}
        inspectionPolicy={inspection}
      />
    </main>,
  );
}

afterEach(cleanup);

it("keeps recorded navigation distinct from a replacement proposal and readiness", () => {
  show(plan());
  const region = screen.getByRole("region", { name: "Contents plan" });
  expect(within(region).getByText("Keep recorded navigation")).toBeTruthy();
  expect(
    within(region).getByRole("list", { name: "Recorded navigation" })
      .textContent,
  ).toContain("Existing opening");
  expect(
    within(region).queryByRole("list", { name: "Proposed navigation" }),
  ).toBeNull();
  expect(
    within(region).getByText("This plan is read-only. The EPUB is unchanged."),
  ).toBeTruthy();
  expect(within(region).getByText("EPUBCheck was not run.")).toBeTruthy();
  expect(within(region).queryByRole("button")).toBeNull();
});

it("shows source-labelled groups and children in a flat proposal with literal paths and source details", () => {
  const child = entry();
  const group = entry({
    label: "First volume",
    origin: "printed_group",
    label_source: {
      path: "EPUB/printed.xhtml",
      source_index: 7,
      document_sha256: "c".repeat(64),
    },
    children: [
      child,
      entry({
        label: "Chapter 2",
        fragment: "two",
        position: { ...child.position, source_index: 9, word_offset: 84 },
      }),
    ],
  });
  show(
    plan({
      decision: "propose",
      reason_codes: ["printed_chapter_targets"],
      entries: [group],
    }),
  );
  const proposed = screen.getByRole("list", { name: "Proposed navigation" });
  const items = within(proposed).getAllByRole("listitem");
  expect(items).toHaveLength(3);
  expect(items[0].textContent).toContain("First volume");
  expect(items[1].textContent).toContain("Within: First volume");
  expect(items[2].textContent).toContain("Chapter 2");
  expect(items[2].textContent).toContain("EPUB/chapter.xhtml#two");
  expect(proposed.querySelector("ol, a")).toBeNull();
  fireEvent.click(within(items[0]).getByText("Source details"));
  expect(within(items[0]).getByText("EPUB/printed.xhtml")).toBeTruthy();
  expect(within(items[0]).getByText("c".repeat(64))).toBeTruthy();
  expect(within(items[0]).getByText("7")).toBeTruthy();
  fireEvent.click(within(items[1]).getByText("Source details"));
  expect(within(items[1]).getAllByText("0")).toHaveLength(2);
});

it("marks a needed anchor without inventing a fragment or an applied edit", () => {
  show(
    plan({
      decision: "propose",
      entries: [entry({ fragment: null, requires_anchor: true })],
    }),
  );
  const proposed = screen.getByRole("list", { name: "Proposed navigation" });
  expect(within(proposed).getByText("New anchor required")).toBeTruthy();
  expect(within(proposed).getAllByText("EPUB/chapter.xhtml")).toHaveLength(2);
  expect(proposed.textContent).not.toContain("EPUB/chapter.xhtml#");
  expect(within(proposed).queryByText(/applied|inserted/i)).toBeNull();
  expect(within(proposed).queryByRole("button")).toBeNull();
});

it("places held reasons beside the disposition and never offers an empty accepted TOC", () => {
  show(
    plan({
      decision: "held",
      reason_codes: ["ambiguous_numbering", "unassigned_chapters"],
    }),
  );
  const region = screen.getByRole("region", { name: "Contents plan" });
  expect(within(region).getByText("Planning held")).toBeTruthy();
  expect(
    within(region).getByRole("list", { name: "Plan reasons" }).textContent,
  ).toMatch(/numbering is ambiguous/);
  expect(
    within(region).getByText(
      "No replacement list is proposed while planning is held.",
    ),
  ).toBeTruthy();
  expect(
    within(region).queryByRole("list", { name: "Proposed navigation" }),
  ).toBeNull();
  expect(within(region).queryByText("No navigation entries")).toBeNull();
});

it.each([undefined, null])(
  "leaves a historical report without a recorded plan unchanged (%s)",
  (value) => {
    show(value);
    const region = screen.getByRole("region", { name: "Contents plan" });
    expect(
      within(region).getByText("Not recorded by this inspection"),
    ).toBeTruthy();
    expect(
      within(region).getByText(
        "Start a new inspection to capture a contents plan.",
      ),
    ).toBeTruthy();
    expect(within(region).queryByRole("list")).toBeNull();
    expect(within(region).queryByRole("button")).toBeNull();
  },
);

it.each([
  ["unsupported decision", { decision: "automatic" }],
  ["unsupported planner", { policy_version: "librarium.contents-plan.v99" }],
  ["different source", { source_sha256: "d".repeat(64) }],
  [
    "different inspection",
    { inspection_policy: "librarium.epub-structure.v3" },
  ],
  ["readiness claim", { ready: true }],
  ["empty proposal", { decision: "propose", entries: [] }],
  [
    "partial held proposal",
    { decision: "held", entries: [entry({ label: "Partial output" })] },
  ],
])(
  "shows an unavailable plan for %s without interpreting its entries",
  (_name, change) => {
    show({ ...plan(), ...change } as EpubContentsPlan);
    const region = screen.getByRole("region", { name: "Contents plan" });
    expect(within(region).getByText("Plan unavailable")).toBeTruthy();
    expect(within(region).queryByText("Existing opening")).toBeNull();
    expect(within(region).queryByText("Partial output")).toBeNull();
    expect(
      within(region).queryByRole("list", { name: "Proposed navigation" }),
    ).toBeNull();
  },
);

it("escapes labels, preserves long group context and exposes unknown reasons without guessing", () => {
  const label = (
    "<img src=x onerror=alert(1)>" + "Long source label ".repeat(20)
  ).trim();
  show(
    plan({
      decision: "propose",
      reason_codes: ["future_reason_code"],
      existing: [
        {
          label: "<script>source</script>",
          path: "EPUB/chapter.xhtml",
          fragment: null,
          kind: "ncx",
          ancestors: ["Recorded group"],
        },
      ],
      entries: [entry({ label, children: [entry({ label: "Child" })] })],
      excluded_targets: [
        { path: "EPUB/stub.xhtml", fragment: null, reason: "future_exclusion" },
      ],
    }),
  );
  const region = screen.getByRole("region", { name: "Contents plan" });
  expect(within(region).getByText(label)).toBeTruthy();
  expect(within(region).getByText(`Within: ${label}`)).toBeTruthy();
  expect(
    within(region).getByText("Recorded reason: future_reason_code"),
  ).toBeTruthy();
  expect(region.querySelector("img, script, a")).toBeNull();
  fireEvent.click(within(region).getByText("Excluded targets (1)"));
  expect(
    within(region).getByText("Recorded reason: future_exclusion"),
  ).toBeTruthy();
});

it("treats prototype-shaped reason and origin codes as literal unknown values", () => {
  show(
    plan({
      decision: "propose",
      reason_codes: ["constructor"],
      entries: [entry({ origin: "__proto__" })],
      excluded_targets: [
        { path: "EPUB/stub.xhtml", fragment: null, reason: "__proto__" },
      ],
    }),
  );
  const region = screen.getByRole("region", { name: "Contents plan" });
  expect(within(region).getByText("Recorded reason: constructor")).toBeTruthy();
  fireEvent.click(within(region).getByText("Source details"));
  expect(within(region).getByText("__proto__")).toBeTruthy();
  fireEvent.click(within(region).getByText("Excluded targets (1)"));
  expect(within(region).getByText("Recorded reason: __proto__")).toBeTruthy();
});

it("retains semantic accessibility for a grouped proposal and its source disclosures", async () => {
  show(
    plan({
      decision: "propose",
      entries: [
        entry({
          label: "Volume",
          children: [entry({ fragment: null, requires_anchor: true })],
        }),
      ],
    }),
  );
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

it("explains a v2 held plan with Library Finish's rule findings and measures", async () => {
  show(
    plan({
      policy_version: "librarium.contents-plan.v2",
      decision: "held",
      reason_codes: ["numbering_unsettled", "ocr_scan"],
      measures: {
        existing: 4,
        headings: 31,
        linked: 31,
        entries: 31,
        words: 98000,
      },
      problems: ["chapter 7 missing before Chapter 9"],
    }),
  );
  const region = screen.getByRole("region", { name: "Contents plan" });
  expect(within(region).getByText("Planning held")).toBeTruthy();
  expect(
    within(region).getByText(
      "The chapter numbering has gaps or repeats the rules cannot settle.",
    ),
  ).toBeTruthy();
  expect(
    within(region).getByText(
      "This is an automatic OCR scan; a better copy is needed.",
    ),
  ).toBeTruthy();
  const findings = within(region).getByRole("list", { name: "Rule findings" });
  expect(findings.textContent).toBe("chapter 7 missing before Chapter 9");
  fireEvent.click(within(region).getByText("Plan provenance"));
  expect(within(region).getByText("Chapter headings found")).toBeTruthy();
  expect(within(region).getByText((98000).toLocaleString())).toBeTruthy();
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

it("names v2 entry origins and refuses malformed v2 measures", () => {
  const proposal = plan({
    policy_version: "librarium.contents-plan.v2",
    decision: "propose",
    reason_codes: ["chapter_headings"],
    entries: [entry({ origin: "joined_label" })],
    problems: [],
  });
  show(proposal);
  const region = screen.getByRole("region", { name: "Contents plan" });
  expect(
    within(region).getByText("Rebuilt from the book's chapter headings."),
  ).toBeTruthy();
  expect(
    within(region).queryByRole("list", { name: "Rule findings" }),
  ).toBeNull();
  fireEvent.click(within(region).getByText("Source details"));
  expect(
    within(region).getByText("Heading joined with its subtitle"),
  ).toBeTruthy();
  cleanup();
  show({
    ...proposal,
    measures: { existing: 1, headings: 1, linked: 1, entries: 1 } as never,
  });
  expect(screen.getByText("Plan unavailable")).toBeTruthy();
});
