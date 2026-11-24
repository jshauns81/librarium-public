// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { SourceAttribution } from "../src/SourceAttribution";
import {
  sourceAttributionBinds,
  reportBinds,
} from "../src/file-inspection-api";
import type { EpubReport, Job } from "../src/types";

afterEach(cleanup);
const sha = "a".repeat(64);
export function titleReport(): EpubReport {
  return {
    source_sha256: sha,
    inspection_complete: true,
    package: { path: "EPUB/package.opf", version: "3.0", byte_sha256: sha },
    identifier_evidence: {
      schema_version: "librarium.epub-identifiers.v1",
      package_path: "EPUB/package.opf",
      package_version: "3.0",
      package_sha256: sha,
      unique_identifier: null,
      prefix: null,
      entries: [],
      refinements: [],
    },
    policy: { version: "librarium.epub-structure.v7" },
    structural_check: "passed",
    spine: [
      { index: 0, idref: "title", path: "EPUB/title.xhtml", linear: "yes" },
    ],
    documents: [
      { path: "EPUB/title.xhtml", byte_sha256: sha, source_element_count: 8 },
    ],
    source_attribution: {
      policy: "librarium.epub-source-attribution.v1",
      status: "recorded",
      source_sha256: sha,
      reason: null,
      scope: "Bounded source labels only.",
      observations: [
        {
          id: "source-title-1",
          spine_index: 0,
          path: "EPUB/title.xhtml",
          resource_sha256: sha,
          source_index: 3,
          rule: "semantic_titlepage",
          scope: "container_candidate",
          title: {
            text: "The Last Orchard",
            source_index: 4,
            marker: "doc-title",
          },
          credits: [
            { text: "Mara Quill", source_index: 5, marker: "docauthor" },
          ],
        },
      ],
    },
  };
}
it.each(["librarium.epub-structure.v7", "librarium.epub-structure.v8"])(
  "shows literal labels, source positions and the whole-file limit under %s",
  async (version) => {
    const report = titleReport();
    report.policy!.version = version;
    expect(sourceAttributionBinds(report)).toBe(true);
    const { container } = render(<SourceAttribution report={report} />);
    expect(screen.getByText("The Last Orchard")).toBeTruthy();
    expect(screen.getByText("Mara Quill")).toBeTruthy();
    expect(
      screen.getByText(/whole-file identity remains unconfirmed/i),
    ).toBeTruthy();
    expect(screen.getByText(/Source element 4/)).toBeTruthy();
    const result = await axe.run(container, {
      rules: { "color-contrast": { enabled: false } },
    });
    expect(result.violations).toEqual([]);
  },
);
it.each(["source", "resource", "position", "duplicate", "history", "missing"])(
  "refuses mismatched %s evidence before displaying the report",
  (field) => {
    const report = titleReport();
    const evidence = report.source_attribution!;
    if (field === "source") evidence.source_sha256 = "b".repeat(64);
    if (field === "resource")
      evidence.observations[0].resource_sha256 = "b".repeat(64);
    if (field === "position") evidence.observations[0].title!.source_index = 8;
    if (field === "duplicate")
      evidence.observations.push(evidence.observations[0]);
    if (field === "history")
      report.policy!.version = "librarium.epub-structure.v6";
    if (field === "missing") delete report.source_attribution;
    expect(sourceAttributionBinds(report)).toBe(false);
    const job = {
      id: "job",
      source_version: report.policy!.version,
      source_sha256: sha,
      result: { report_sha256: sha },
    } as Job;
    expect(
      reportBinds(job, {
        job_id: "job",
        source_sha256: sha,
        report_sha256: sha,
        report,
      }),
    ).toBe(false);
  },
);
it("keeps historical absence and current unknown distinct", () => {
  const report = titleReport();
  report.policy!.version = "librarium.epub-structure.v6";
  delete report.source_attribution;
  const view = render(<SourceAttribution report={report} />);
  expect(screen.getByText(/Not recorded by this inspection/)).toBeTruthy();
  report.policy!.version = "librarium.epub-structure.v7";
  report.source_attribution = {
    ...titleReport().source_attribution!,
    status: "unconfirmed",
    observations: [],
    reason: "no_title_evidence",
  };
  view.rerender(<SourceAttribution report={report} />);
  expect(screen.getByText(/No eligible title and credit block/)).toBeTruthy();
  expect(screen.queryByText("The Last Orchard")).toBeNull();
});
