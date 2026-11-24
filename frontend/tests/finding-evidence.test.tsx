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
import { JobProgress } from "../src/JobProgress";
import { FindingEvidence } from "../src/FindingEvidence";
import type { Job } from "../src/types";

afterEach(cleanup);
const finding = {
  name: "Source agreement",
  ok: false,
  status: "attention" as const,
  detail: "Sources disagree. This does not establish which value is correct.",
  items: [
    {
      field: "first_published",
      value: 0,
      value_truncated: false,
      agree: ["source-one"],
      agree_count: 2,
      disagree: [
        {
          origin: "source-two",
          value: "A longer recorded excerpt…",
          value_truncated: true,
        },
      ],
      disagree_count: 3,
    },
  ],
};
const job = {
  title: "Synthetic review",
  kind: "catalogue",
  state: "succeeded",
  result: { findings: [finding] },
  message: "Saved",
  updated_at: "2026-11-02T12:00:00Z",
} as unknown as Job;

it("keeps unfamiliar evidence and false, missing and empty values inspectable", () => {
  const other = {
    ...job,
    result: {
      findings: [
        {
          ...finding,
          items: [
            { field: "unfamiliar", value: false, extra: [0, null, [], {}] },
          ],
        },
      ],
    },
  } as unknown as Job;
  render(<JobProgress job={other} />);
  fireEvent.click(screen.getByText("Finding details"));
  expect(screen.getByText("false")).toBeTruthy();
  expect(screen.getByText("Not recorded")).toBeTruthy();
  expect(screen.getByText("Empty list")).toBeTruthy();
  expect(screen.getByText("Empty object")).toBeTruthy();
});

it("corrects the singular excerpt wording in historical summaries without changing the recorded counts", () => {
  render(
    <JobProgress
      job={
        {
          ...job,
          result: {
            findings: [
              {
                ...finding,
                detail:
                  "1 recorded values are shown as excerpts of at most 160 characters; 21 recorded values are retained.",
              },
            ],
          },
        } as unknown as Job
      }
    />,
  );
  fireEvent.click(screen.getByText("Finding details"));
  expect(
    screen.getByText(
      "1 recorded value is shown as an excerpt of at most 160 characters; 21 recorded values are retained.",
    ),
  ).toBeTruthy();
});

it("states an identical saved scope once while preserving a distinct record scope", () => {
  const scope =
    "Structural checks only; ownership and library changes are outside this check.";
  const view = render(
    <JobProgress
      job={
        {
          ...job,
          result: {
            scope,
            findings: [
              {
                ...finding,
                name: "Scope of this check",
                detail: scope,
                items: [],
              },
            ],
          },
        } as unknown as Job
      }
    />,
  );
  fireEvent.click(screen.getByText("Finding details"));
  fireEvent.click(screen.getByText("Review record"));
  expect(screen.getAllByText(scope)).toHaveLength(1);
  expect(screen.getByText("Scope appears in Finding details.")).toBeTruthy();
  view.rerender(
    <JobProgress
      job={
        {
          ...job,
          result: {
            scope:
              "The saved inspection stopped before all documents were read.",
            findings: [
              {
                ...finding,
                name: "Scope of this check",
                detail: scope,
                items: [],
              },
            ],
          },
        } as unknown as Job
      }
    />,
  );
  expect(
    screen.getByText(
      "The saved inspection stopped before all documents were read.",
    ),
  ).toBeTruthy();
  expect(screen.queryByText("Scope appears in Finding details.")).toBeNull();
});

it.each(["queued", "running"] as const)(
  "does not offer an empty finding disclosure for a %s record",
  (state) => {
    render(
      <JobProgress
        job={
          {
            ...job,
            state,
            result: { findings: [], scope: "Metadata comparison only." },
          } as unknown as Job
        }
      />,
    );
    expect(screen.queryByText("Finding details")).toBeNull();
    expect(screen.queryByRole("list")).toBeNull();
    expect(screen.queryByText(/No findings|No issues/)).toBeNull();
    fireEvent.click(screen.getByText("Review record"));
    expect(screen.getByText("Metadata comparison only.")).toBeTruthy();
  },
);

function sourceRecord(value: unknown, overrides: Record<string, unknown> = {}) {
  return {
    field: "tag",
    value,
    value_truncated: false,
    agree: ["source-one"],
    agree_count: 1,
    disagree: [],
    disagree_count: 0,
    ...overrides,
  };
}

function rows(table: HTMLElement) {
  return within(table)
    .getAllByRole("row")
    .slice(1)
    .map((row) => {
      const [value, sources] = row.querySelectorAll("th, td");
      return [
        value.querySelector(".source-value")!.textContent,
        [...sources.querySelectorAll("li")].map((li) => li.textContent),
      ];
    });
}

// Shaped like a saved catalogue review: one record per distinct value, with
// each disagreeing source's values stored as JSON text.
const authorRecords = [
  sourceRecord("Writer A", {
    field: "author",
    agree: ["openlibrary", "publisher-feed"],
    agree_count: 2,
    disagree: ["audible", "goodreads", "lexicanum"].map((origin) => ({
      origin,
      value: '["Writer C"]',
      value_truncated: false,
    })),
    disagree_count: 3,
  }),
  sourceRecord("Writer B", {
    field: "author",
    agree: ["openlibrary", "publisher-feed"],
    agree_count: 2,
    disagree: ["audible", "goodreads", "lexicanum"].map((origin) => ({
      origin,
      value: '["Writer C"]',
      value_truncated: false,
    })),
    disagree_count: 3,
  }),
];

it("shows each field as distinct values and the sources that record them", async () => {
  render(
    <JobProgress
      job={
        {
          ...job,
          result: { findings: [{ ...finding, items: authorRecords }] },
        } as unknown as Job
      }
    />,
  );
  fireEvent.click(screen.getByText("Finding details"));
  const table = screen.getByRole("table", { name: "Author" });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent),
  ).toEqual(["Value", "Supported by"]);
  // Agreement is resolved by compatibility, so support never claims an exact match.
  expect(
    screen.getAllByText(
      "A supporting source may record a compatible form, such as a year for a full date.",
    ),
  ).toHaveLength(1);
  expect(rows(table)).toEqual([
    ["Writer C", ["audible", "goodreads", "lexicanum"]],
    ["Writer A", ["openlibrary", "publisher-feed"]],
    ["Writer B", ["openlibrary", "publisher-feed"]],
  ]);
  const shown = table
    .closest(".source-comparisons")!
    .cloneNode(true) as Element;
  shown.querySelector(".source-raw")!.remove();
  for (const text of ["value_truncated", "agree_count", '["Writer C"]'])
    expect(shown.textContent).not.toContain(text);
  expect(
    (await axe.run(document.body)).violations.filter((v) => v.id !== "region"),
  ).toEqual([]);
});

it("keeps the exact saved records in one collapsed raw view", () => {
  render(<FindingEvidence name="Source agreement" items={authorRecords} />);
  const raw = screen.getByText("Raw record").closest("details")!;
  expect(raw.open).toBe(false);
  const block = within(raw).getByRole("region", {
    name: "Raw source agreement records",
  });
  expect(block.tabIndex).toBe(0);
  expect(block.textContent).toBe(
    authorRecords.map((item) => JSON.stringify(item)).join("\n"),
  );
});

it("lists a source under every value it recorded, including values from older list shapes", () => {
  render(
    <FindingEvidence
      name="Source agreement"
      items={[
        sourceRecord("2006", {
          field: "first_published",
          agree: ["openlibrary"],
          disagree: [
            { origin: "openlibrary", value: "2011", value_truncated: false },
            { origin: "openlibrary", value: "2014", value_truncated: false },
          ],
          disagree_count: 2,
        }),
        sourceRecord("Reader A", {
          field: "narrator",
          agree: ["audible", "lexicanum"],
          agree_count: 2,
          disagree: [
            {
              origin: "goodreads",
              value: ["Reader B", "Reader C"],
              value_truncated: false,
            },
          ],
          disagree_count: 1,
        }),
      ]}
    />,
  );
  expect(rows(screen.getByRole("table", { name: "First published" }))).toEqual([
    ["2006", ["openlibrary"]],
    ["2011", ["openlibrary"]],
    ["2014", ["openlibrary"]],
  ]);
  expect(rows(screen.getByRole("table", { name: "Narrator" }))).toEqual([
    ["Reader A", ["audible", "lexicanum"]],
    ["Reader B", ["goodreads"]],
    ["Reader C", ["goodreads"]],
  ]);
});

it("marks excerpts and never merges excerpts from different sources", () => {
  const opening = "The same captured opening…";
  render(
    <FindingEvidence
      name="Source agreement"
      items={[
        sourceRecord(opening, {
          field: "synopsis",
          value_truncated: true,
          disagree: [
            { origin: "source-two", value: opening, value_truncated: true },
            {
              origin: "source-three",
              value: '["A cut list value tha…',
              value_truncated: true,
            },
          ],
          disagree_count: 2,
        }),
      ]}
    />,
  );
  const table = screen.getByRole("table", { name: "Synopsis" });
  expect(rows(table)).toEqual([
    [opening, ["source-one"]],
    [opening, ["source-two"]],
    ['["A cut list value tha…', ["source-three"]],
  ]);
  expect(
    within(table).getAllByText("Excerpt; full value not captured"),
  ).toHaveLength(3);
});

it("says once when a field has source records that are not listed", () => {
  render(
    <FindingEvidence
      name="Source agreement"
      items={[
        sourceRecord("Shown", { agree_count: 3 }),
        sourceRecord("Also shown", { disagree_count: 4 }),
      ]}
    />,
  );
  expect(
    screen.getAllByText(
      "Some source records for this field are counted but not listed.",
    ),
  ).toHaveLength(1);
});

it("keeps distinct value types apart and shows a record with no source", () => {
  render(
    <FindingEvidence
      name="Source agreement"
      items={[
        sourceRecord(false),
        sourceRecord("false"),
        sourceRecord([]),
        sourceRecord(null, { agree: [], agree_count: 0 }),
      ]}
    />,
  );
  const table = screen.getByRole("table", { name: "Tag" });
  expect(within(table).getAllByText("false")).toHaveLength(2);
  expect(within(table).getByText("Boolean")).toBeTruthy();
  expect(within(table).getByText("Text")).toBeTruthy();
  expect(within(table).getByText("Empty list")).toBeTruthy();
  expect(within(table).getByText("Not recorded")).toBeTruthy();
  expect(within(table).getByText("No source listed")).toBeTruthy();
});

it("previews long values with an explicit control", () => {
  const long = "A complete captured synopsis. ".repeat(30);
  render(
    <FindingEvidence
      name="Source agreement"
      items={[sourceRecord(long, { field: "synopsis" })]}
    />,
  );
  const toggle = screen.getByRole("button", {
    name: "Read captured Synopsis value",
  });
  const value = document.getElementById(toggle.getAttribute("aria-controls")!)!;
  expect(value.textContent).toBe(long);
  expect(value.classList.contains("is-preview")).toBe(true);
  fireEvent.click(toggle);
  expect(toggle.getAttribute("aria-expanded")).toBe("true");
  expect(value.classList.contains("is-preview")).toBe(false);
});

it("shows extra recorded qualifiers beside the value they qualify", () => {
  render(
    <FindingEvidence
      name="Source agreement"
      items={[
        sourceRecord("Supported", {
          edition: "edition-one",
          disagree: [
            {
              origin: "source-two",
              value: "Alternate",
              value_truncated: false,
              capture_rule: "rule-two",
            },
          ],
          disagree_count: 1,
        }),
      ]}
    />,
  );
  const table = screen.getByRole("table", { name: "Tag" });
  const supported = within(table).getByText("Supported").closest("tr")!;
  expect(within(supported).getByText("edition: edition-one")).toBeTruthy();
  const alternate = within(table).getByText("Alternate").closest("tr")!;
  expect(within(alternate).getByText("capture_rule: rule-two")).toBeTruthy();
});

it("shows flat finding items such as ISBN problems as a table", () => {
  const items = [
    { value: "9780000000002", problem: "duplicate_isbn13", edition_id: "e_1" },
    { value: "9780000000002", problem: "duplicate_isbn13", edition_id: "e_2" },
  ];
  render(<FindingEvidence name="ISBN checks" items={items} />);
  const table = screen.getByRole("table", { name: "ISBN checks items" });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent),
  ).toEqual(["Value", "Problem", "Edition id"]);
  expect(within(table).getAllByRole("row")).toHaveLength(3);
  expect(within(table).getByText("e_2")).toBeTruthy();
});
