// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { JobProgress } from "../src/JobProgress";
import { RETIRED_KINDS, retiredKindLabel } from "../src/retired-kinds";
import type { Job } from "../src/types";

afterEach(cleanup);
const job = (overrides: Partial<Job> = {}): Job => ({
  id: "11111111-1111-4111-8111-111111111111",
  kind: "epub",
  request_key: "key",
  work_id: "a".repeat(64),
  title: "Old record",
  state: "succeeded",
  revision: 3,
  checkpoint: 4,
  attempts: 1,
  message: "Finished earlier",
  result: {},
  updated_at: "2026-11-01T12:00:00Z",
  source_version: "librarium.epub-structure.v5",
  source_sha256: "a".repeat(64),
  input_fingerprint: "b".repeat(64),
  ...overrides,
});

it.each(RETIRED_KINDS)(
  "shows an old %s job as a plain record with no report, progress or control",
  (kind) => {
    const { container } = render(<JobProgress job={job({ kind })} />);
    expect(screen.getByText("Complete")).toBeTruthy();
    expect(screen.getByText("Finished earlier")).toBeTruthy();
    expect(
      screen.getByText(
        new RegExp(`${retiredKindLabel(kind)} record from a retired feature`),
      ),
    ).toBeTruthy();
    expect(container.querySelector("button, progress, details")).toBeNull();
  },
);
it("does not render a retired job that never finished as live progress", () => {
  const { container } = render(
    <JobProgress
      job={job({ kind: "epub_delivery", state: "running", attempts: 2 })}
    />,
  );
  expect(screen.getByText("Running")).toBeTruthy();
  expect(container.querySelector("progress")).toBeNull();
});
it("shows a failed retired job without an error alert or retry", () => {
  render(
    <JobProgress
      job={job({
        kind: "epub_correction",
        state: "failed",
        message: "Could not finish",
      })}
    />,
  );
  expect(screen.getByText("Failed")).toBeTruthy();
  expect(screen.getByText("Could not finish")).toBeTruthy();
  expect(screen.queryByRole("alert")).toBeNull();
  expect(screen.queryByRole("button")).toBeNull();
});
it("renders a job of an unknown kind instead of crashing", () => {
  render(
    <JobProgress
      job={job({ kind: "kind_from_a_newer_release" as Job["kind"] })}
    />,
  );
  expect(screen.getByText("Complete")).toBeTruthy();
  render(<JobProgress job={job({ kind: undefined, result: {} })} />);
  expect(screen.getAllByText("Complete")).toHaveLength(2);
});
it("has no accessibility violations for a retired record", async () => {
  const { container } = render(
    <main>
      <h1>History</h1>
      <JobProgress job={job({ kind: "output_validation" })} />
    </main>,
  );
  expect(
    (
      await axe.run(container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});
