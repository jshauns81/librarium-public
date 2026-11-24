// @vitest-environment jsdom
import React from "react";
import { sourceLabel } from "../src/catalogue-sources";
import { afterEach, expect, it, vi } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import {
  CoverWork,
  SourceNote,
  Week,
  type Telemetry,
} from "../src/CatalogueGlance";

afterEach(cleanup);

it("uses display names and preserves unknown IDs including object property names", () => {
  expect(
    ["isbngrid", "isbndb", "openlibrary", "goodreads", "hardcover"].map(
      sourceLabel,
    ),
  ).toEqual(["ISBNgrid", "ISBNdb", "Open Library", "Goodreads", "Hardcover"]);
  expect(sourceLabel("new-source")).toBe("new-source");
  expect(sourceLabel("constructor")).toBe("constructor");
});
const telemetry: Telemetry = {
  state: "observed",
  fetched_at: "2026-11-10T12:00:00Z",
  age_seconds: 0,
  failure: "",
  status: { live: { state: "idle" }, cycles: [] },
  covers: {
    upscale: {
      enabled: true,
      paused: false,
      state: "idle",
      completed: 3,
      queued: 2,
      failed: 0,
    },
  },
};

it("groups switched-off sources with display names and one shared reason", () => {
  render(
    <SourceNote
      telemetry={{
        ...telemetry,
        status: {
          ...telemetry.status,
          cycles: [
            {
              started_at: telemetry.fetched_at,
              tripped: ["isbngrid", "isbndb", "openlibrary", "new-source"],
              tripped_reasons: {
                isbngrid: "API key rejected (401)",
                isbndb: "API key rejected (401)",
                openlibrary: "Rate limit reached (429)",
              },
            },
          ],
        },
      }}
    />,
  );
  expect(screen.getByRole("note").textContent).toContain(
    "ISBNgrid and ISBNdb are switched off: API keys rejected (401).",
  );
  expect(screen.getByRole("note").textContent).toContain(
    "Open Library is switched off: Rate limit reached (429).",
  );
  expect(screen.getByRole("note").textContent).toContain(
    "new-source is switched off: Source unavailable.",
  );
  expect(screen.getByRole("note").textContent?.match(/rejected/g)).toHaveLength(
    1,
  );
});

it.each([
  undefined,
  { state: "unavailable" as const, reason: "Status is not configured." },
  { state: "unavailable" as const, reason: "Waiting for the first poll." },
])(
  "does not claim an empty day when cycle history is unavailable: %j",
  (value) => {
    render(<Week telemetry={value} checkedAt={telemetry.fetched_at} />);
    const note = document.querySelector(".health-day-note");
    expect(note?.textContent).toContain("Cycle history is unavailable");
    if (value) expect(note?.textContent).toContain(value.reason);
    expect(note?.textContent).not.toContain("No cycle is recorded");
    fireEvent.click(screen.getAllByRole("button")[0]);
    expect(note?.textContent).toContain("Cycle history is unavailable");
  },
);

it("distinguishes an observed empty day from unavailable history", () => {
  render(<Week telemetry={telemetry} checkedAt={telemetry.fetched_at} />);
  expect(document.querySelector(".health-day-note")?.textContent).toContain(
    "No cycle is recorded",
  );
});

it.each([
  [{ paused: true }, "upscaling is paused"],
  [{ enabled: false }, "upscaling is disabled"],
  [{ state: "working" }, "the upscaler is working"],
  [{ failed: 2 }, "some need attention"],
])("shows cover work state %j", (upscale, expected) => {
  render(
    <CoverWork
      telemetry={{
        ...telemetry,
        covers: { upscale: { ...telemetry.covers.upscale, ...upscale } },
      }}
      examples={[]}
      openWork={vi.fn()}
    />,
  );
  expect(screen.getByText(new RegExp(expected))).toBeTruthy();
  expect(screen.getByRole("progressbar").getAttribute("value")).toBe("3");
});

it("qualifies stale cover work and keeps missing counts unavailable", () => {
  const view = render(
    <CoverWork
      telemetry={{ ...telemetry, state: "stale", age_seconds: 600 }}
      examples={[]}
      openWork={vi.fn()}
    />,
  );
  expect(screen.getByText(/^At last report, 3/)).toBeTruthy();
  view.rerender(
    <CoverWork
      telemetry={{ ...telemetry, covers: { upscale: {} } }}
      examples={[]}
      openWork={vi.fn()}
    />,
  );
  expect(screen.getByText("Cover progress is unavailable.")).toBeTruthy();
  expect(screen.queryByRole("progressbar")).toBeNull();
});
