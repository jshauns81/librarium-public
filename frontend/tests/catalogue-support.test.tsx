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
import {
  CatalogueSupport,
  type CatalogueSupportRecord,
} from "../src/CatalogueSupport";

afterEach(() => {
  cleanup();
  history.replaceState(null, "", "/");
});

function open(records: CatalogueSupportRecord[]) {
  const view = render(<CatalogueSupport records={records} />);
  fireEvent.click(screen.getByText(/^Source support/));
  return view;
}

it("groups repeated fields and source values without losing their exact recorded-value relationships", () => {
  const otherTags = ["History", "Space travel"];
  open([
    {
      field: "tag",
      value: "Adventure",
      agree: ["publisher-feed"],
      disagree: [{ origin: "openlibrary", value: otherTags }],
    },
    {
      field: "tag",
      value: "War",
      agree: ["publisher-feed"],
      disagree: [{ origin: "openlibrary", value: otherTags }],
    },
    {
      field: "tag",
      value: "Adventure",
      agree: ["goodreads"],
      disagree: [{ origin: "openlibrary", value: otherTags }],
    },
    {
      field: "title",
      value: "Fixture: Signal Archive",
      agree: ["lexicanum"],
      disagree: [],
    },
  ]);
  expect(
    screen.getByText("Source support · 2 fields · 3 disputed records"),
  ).toBeTruthy();
  expect(
    screen.getByText("4 captured records, grouped by field."),
  ).toBeTruthy();
  const tags = screen.getByRole("region", { name: "Tags" });
  const table = within(tags).getByRole("table", { name: "Recorded values" });
  expect(within(table).getAllByText("Adventure")).toHaveLength(1);
  expect(within(table).getByText("publisher-feed, goodreads")).toBeTruthy();
  const comparisons = within(tags).getByRole("list", {
    name: "Different source values",
  });
  expect(within(comparisons).getAllByText("openlibrary")).toHaveLength(1);
  expect(within(comparisons).getAllByText("History")).toHaveLength(1);
  expect(within(comparisons).getByText("Space travel")).toBeTruthy();
  const links = within(comparisons).getAllByRole("link");
  const targets = links.map((link) =>
    document.getElementById(link.getAttribute("href")!.slice(1))!,
  );
  expect(targets).toHaveLength(2);
  expect(targets[0].textContent).toContain("Adventure");
  expect(targets[1].textContent).toContain("War");
  fireEvent.click(links[0]);
  expect(document.activeElement).toBe(targets[0]);
  expect(location.hash).toBe("");
  const raw = screen
    .getByText("Captured source records · 4")
    .closest("details")!;
  expect(raw.open).toBe(false);
  fireEvent.click(within(raw).getByText("Captured source records · 4"));
  expect(within(raw).getAllByText("Adventure")).toHaveLength(2);
});

it("keeps literal zero, false, null, missing, empty text and empty containers distinct", () => {
  open(
    [0, "0", false, null, undefined, "", [], {}].map((value) => ({
      field: "identifier",
      value,
      agree: [],
      disagree: [],
    })),
  );
  const group = screen.getByRole("region", { name: "Identifier" });
  expect(within(group).getAllByText("0")).toHaveLength(2);
  expect(within(group).getByText("false")).toBeTruthy();
  expect(within(group).getByText("Not recorded")).toBeTruthy();
  expect(within(group).getByText("Not supplied")).toBeTruthy();
  expect(within(group).getByText("Empty text")).toBeTruthy();
  expect(within(group).getByText("Empty list")).toBeTruthy();
  expect(within(group).getByText("Empty object")).toBeTruthy();
  expect(
    within(group).getAllByText("No supporting source recorded"),
  ).toHaveLength(8);
});

it("reveals a full long source value without changing or repeating it", () => {
  const text = "A fictional expedition follows a distant signal. ".repeat(20);
  const view = open([
    { field: "synopsis", value: text, agree: ["fixture-source"], disagree: [] },
  ]);
  const button = screen.getByRole("button", {
    name: "Read full recorded synopsis 1",
  });
  const paragraph = document.getElementById(
    button.getAttribute("aria-controls")!,
  )!;
  expect(paragraph.textContent).toBe(text);
  expect(button.getAttribute("aria-expanded")).toBe("false");
  fireEvent.click(button);
  expect(
    screen
      .getByRole("button", { name: "Show less recorded synopsis 1" })
      .getAttribute("aria-expanded"),
  ).toBe("true");
  expect(paragraph.textContent).toBe(text);
  expect(
    view.container.querySelectorAll(".catalogue-source-text"),
  ).toHaveLength(1);
});

it("places supporting sources before long recorded values in the reading order", () => {
  open([
    {
      field: "synopsis",
      value: "Captured narrative. ".repeat(40),
      agree: ["fixture-source"],
      disagree: [],
    },
  ]);
  const table = screen.getByRole("table", { name: "Recorded values" });
  expect(
    within(table)
      .getAllByRole("columnheader")
      .map((header) => header.textContent),
  ).toEqual(["Supporting sources", "Recorded value"]);
  const cells = within(table).getAllByRole("cell");
  expect(cells[0].textContent).toContain("fixture-source");
  expect(cells[1].textContent).toContain("Captured narrative.");
  expect(
    cells[0].querySelector(".catalogue-source-cell-label")?.textContent,
  ).toBe("Supporting sources");
  expect(
    cells[1].querySelector(".catalogue-source-cell-label")?.textContent,
  ).toBe("Recorded value");
});

it("states an empty evidence result without inventing agreement", async () => {
  const view = open([]);
  expect(screen.getByText("No source support recorded.")).toBeTruthy();
  expect(screen.queryByRole("table")).toBeNull();
  expect(
    (
      await axe.run(view.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});
