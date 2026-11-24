// @vitest-environment jsdom
import React from "react";
import { afterEach, expect, it } from "vitest";
import { cleanup, fireEvent, render, screen } from "@testing-library/react";
import axe from "axe-core";
import { IdentifierDeclarations } from "../src/IdentifierDeclarations";
import {
  identifierEvidenceBinds,
  reportBinds,
} from "../src/file-inspection-api";
import type { EpubReport, Job } from "../src/types";

afterEach(cleanup);
const sha = "a".repeat(64);
export const capturedReport = (): EpubReport => ({
  policy: {
    version: "librarium.epub-structure.v5",
    limits: {
      max_metadata_chars: 256,
      max_field_chars: 512,
      max_records: 8192,
      max_xml_nodes: 100000,
    },
  },
  source_sha256: sha,
  inspection_complete: true,
  package: { path: "EPUB/package.opf", version: "3.0", byte_sha256: sha },
  metadata: [
    { name: "identifier", text: "9780306406157" },
    { name: "identifier", text: "" },
  ],
  identifier_evidence: {
    schema_version: "librarium.epub-identifiers.v1",
    package_path: "EPUB/package.opf",
    package_version: "3.0",
    package_sha256: sha,
    unique_identifier: "book-id",
    prefix: "custom: https://example.invalid/vocab/",
    entries: [
      {
        source_index: 3,
        value: "9780306406157",
        id: "book-id",
        xml_id: null,
        opf_scheme: "ISBN",
        id_count: 1,
        xml_id_count: 0,
        text_only: true,
      },
      {
        source_index: 5,
        value: "",
        id: "",
        xml_id: "xml-token",
        opf_scheme: "",
        id_count: 1,
        xml_id_count: 1,
        text_only: false,
      },
    ],
    refinements: [
      {
        source_index: 4,
        property: "identifier-type",
        refines: "#book-id",
        scheme: "onix:codelist5",
        value: "15",
        text_only: true,
        target_id: "book-id",
        target_count: 1,
        target_source_index: 3,
        association: "identifier",
      },
      {
        source_index: 7,
        property: "identifier-type",
        refines: "#source",
        scheme: null,
        value: "06",
        text_only: true,
        target_id: "source",
        target_count: 1,
        target_source_index: 6,
        association: "other",
      },
    ],
  },
});

it("distinguishes historical absence, captured empty and incomplete missing evidence", () => {
  const historical: EpubReport = {
    policy: { version: "librarium.epub-structure.v4" },
  };
  const view = render(<IdentifierDeclarations report={historical} />);
  expect(screen.getByText(/Not recorded by this inspection/)).toBeTruthy();
  expect(
    screen.getByText(/new inspection must be explicitly requested/),
  ).toBeTruthy();
  const empty = capturedReport();
  empty.metadata = [];
  empty.identifier_evidence!.entries = [];
  empty.identifier_evidence!.refinements = [];
  view.rerender(<IdentifierDeclarations report={empty} />);
  expect(
    screen.getByText(
      "No identifier declarations or type records were captured in this package.",
    ),
  ).toBeTruthy();
  const partial = {
    ...capturedReport(),
    inspection_complete: false,
    identifier_evidence: null,
  };
  view.rerender(<IdentifierDeclarations report={partial} />);
  expect(
    screen.getByText(/Unavailable from this incomplete inspection/),
  ).toBeTruthy();
  view.rerender(
    <IdentifierDeclarations
      report={{ ...partial, identifier_evidence: undefined }}
    />,
  );
  expect(
    screen.getByText(/Unavailable from this incomplete inspection/),
  ).toBeTruthy();
});

it("shows literal IDs, schemes, pointers and ordered refinements without treating another metadata target as broken", () => {
  render(<IdentifierDeclarations report={capturedReport()} />);
  expect(screen.getByText("9780306406157")).toBeTruthy();
  expect(screen.getAllByText("book-id").length).toBeGreaterThan(0);
  expect(screen.getByText("ISBN")).toBeTruthy();
  expect(screen.getAllByText("Empty").length).toBeGreaterThan(0);
  expect(screen.getAllByText("Not present").length).toBeGreaterThan(0);
  fireEvent.click(screen.getByText("Type records and refinement targets (2)"));
  expect(screen.getByText("Other package element")).toBeTruthy();
  expect(screen.getByText("Identifier target")).toBeTruthy();
  expect(screen.getByText("onix:codelist5")).toBeTruthy();
  expect(screen.getByText(/Contains nested markup/)).toBeTruthy();
  expect(screen.queryByText(/Broken|Invalid ISBN|Unresolved/)).toBeNull();
});

it("escapes long source declarations and passes expanded semantic accessibility", async () => {
  const report = capturedReport();
  report.identifier_evidence!.prefix =
    "<img src=x>" + "\ud83d\udcda".repeat(480);
  render(
    <main>
      <h1>Inspection</h1>
      <h2>Source</h2>
      <h3>Full report</h3>
      <IdentifierDeclarations report={report} />
    </main>,
  );
  fireEvent.click(screen.getByText("Type records and refinement targets (2)"));
  expect(
    document.querySelector(
      ".identifier-declarations img, .identifier-declarations a",
    ),
  ).toBeNull();
  expect(
    (
      await axe.run(document.body, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

it.each([
  "schema",
  "path",
  "digest",
  "version",
  "metadata",
  "order",
  "collision",
  "index",
  "boolean index",
  "text",
  "field",
  "records",
  "association",
  "lower policy",
  "missing",
  "null",
])("refuses malformed v5 declarations: %s", (field) => {
  const report: any = capturedReport();
  const e = report.identifier_evidence;
  if (field === "schema") e.schema_version = "other";
  if (field === "path") e.package_path = "elsewhere.opf";
  if (field === "digest") e.package_sha256 = "b".repeat(64);
  if (field === "version") e.package_version = "2.0";
  if (field === "metadata") report.metadata[0].text = "different";
  if (field === "order") e.entries.reverse();
  if (field === "collision") e.refinements[0].source_index = 3;
  if (field === "index") e.entries[0].source_index = 100000;
  if (field === "boolean index") e.entries[0].source_index = true;
  if (field === "text") e.entries[0].value = "x".repeat(257);
  if (field === "field") e.prefix = "x".repeat(513);
  if (field === "records") e.refinements = Array(8193).fill(e.refinements[0]);
  if (field === "association") e.refinements[0].association = "toString";
  if (field === "lower policy") report.policy.limits.max_metadata_chars = 5;
  if (field === "missing") delete report.identifier_evidence;
  if (field === "null") report.identifier_evidence = null;
  expect(identifierEvidenceBinds(report)).toBe(false);
  const job = {
    id: "job",
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
});

it("retains a refinement of another package element at preorder index zero", () => {
  const report = capturedReport();
  const refinement = report.identifier_evidence!.refinements[1];
  refinement.target_source_index = 0;
  refinement.target_id = "package-root";
  refinement.refines = "#package-root";
  expect(identifierEvidenceBinds(report)).toBe(true);
  render(<IdentifierDeclarations report={report} />);
  fireEvent.click(screen.getByText("Type records and refinement targets (2)"));
  expect(screen.getByText("Other package element")).toBeTruthy();
});

it.each([
  "librarium.epub-structure.v5",
  "librarium.epub-structure.v6",
  "librarium.epub-structure.v7",
  "librarium.epub-structure.v8",
])("discloses and validates captured declarations under %s", (version) => {
  const report = capturedReport();
  report.policy!.version = version;
  if (
    ["librarium.epub-structure.v7", "librarium.epub-structure.v8"].includes(
      version,
    )
  )
    report.source_attribution = {
      policy: "librarium.epub-source-attribution.v1",
      status: "unconfirmed",
      source_sha256: sha,
      reason: "no_title_credit_observations",
      observations: [],
      scope: "Source labels only",
    };
  if (version === "librarium.epub-structure.v8")
    (report as any).document_text_evidence = {
      policy: "librarium.epub-document-text.v1",
      status: "unconfirmed",
      source_sha256: sha,
      documents: [],
      reason: "unsupported_spine_resource",
      scope: "Normalized document body source text only.",
    };
  const job = {
    id: "job",
    source_version: version,
    source_sha256: sha,
    result: { report_sha256: sha },
  } as Job;
  const envelope = {
    job_id: "job",
    source_sha256: sha,
    report_sha256: sha,
    report,
  };
  expect(identifierEvidenceBinds(report)).toBe(true);
  expect(reportBinds(job, envelope)).toBe(true);
  render(<IdentifierDeclarations report={report} />);
  expect(screen.getByText("9780306406157")).toBeTruthy();
  expect(screen.queryByText(/Not recorded by this inspection/)).toBeNull();
  report.identifier_evidence!.package_sha256 = "b".repeat(64);
  expect(identifierEvidenceBinds(report)).toBe(false);
  expect(reportBinds(job, envelope)).toBe(false);
});

it.each(["librarium.epub-structure.v4", "librarium.epub-structure.v5"])(
  "refuses a v6 report bound to a %s job",
  (version) => {
    const report = capturedReport();
    report.policy!.version = "librarium.epub-structure.v6";
    const job = {
      id: "job",
      source_version: version,
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

it("refuses cross-version pre-v5 reports when job.source_version is present while preserving legacy jobs missing source_version", () => {
  const preV5Report: EpubReport = {
    source_sha256: sha,
    inspection_complete: true,
    policy: { version: "librarium.epub-structure.v4" },
  };
  const mismatchedJob = {
    id: "job",
    source_version: "librarium.epub-structure.v3",
    source_sha256: sha,
    result: { report_sha256: sha },
  } as Job;
  expect(
    reportBinds(mismatchedJob, {
      job_id: "job",
      source_sha256: sha,
      report_sha256: sha,
      report: preV5Report,
    }),
  ).toBe(false);

  const matchingJob = {
    ...mismatchedJob,
    source_version: "librarium.epub-structure.v4",
  } as Job;
  expect(
    reportBinds(matchingJob, {
      job_id: "job",
      source_sha256: sha,
      report_sha256: sha,
      report: preV5Report,
    }),
  ).toBe(true);

  const legacyMissingVersionJob = {
    id: "job",
    source_version: "",
    source_sha256: sha,
    result: { report_sha256: sha },
  } as Job;
  expect(
    reportBinds(legacyMissingVersionJob, {
      job_id: "job",
      source_sha256: sha,
      report_sha256: sha,
      report: preV5Report,
    }),
  ).toBe(true);

  const v5Report = capturedReport();
  expect(
    reportBinds(legacyMissingVersionJob, {
      job_id: "job",
      source_sha256: sha,
      report_sha256: sha,
      report: v5Report,
    }),
  ).toBe(false);
});

it("keeps incomplete v6 absence distinct from missing complete evidence", () => {
  const report = capturedReport();
  report.policy!.version = "librarium.epub-structure.v6";
  report.identifier_evidence = null;
  expect(identifierEvidenceBinds(report)).toBe(false);
  report.inspection_complete = false;
  expect(identifierEvidenceBinds(report)).toBe(true);
  render(<IdentifierDeclarations report={report} />);
  expect(
    screen.getByText(/Unavailable from this incomplete inspection/),
  ).toBeTruthy();
});
