import { expect, it } from "vitest";
import { reportBinds } from "../src/file-inspection-api";
import type { Job } from "../src/types";

const sha = "a".repeat(64);
const resource = "b".repeat(64);
function captured(): any {
  return {
    source_sha256: sha,
    policy: { version: "librarium.epub-structure.v8" },
    inspection_complete: true,
    structural_check: "passed",
    metadata: [],
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
    source_attribution: {
      policy: "librarium.epub-source-attribution.v1",
      status: "unconfirmed",
      source_sha256: sha,
      observations: [],
      reason: "no_title_evidence",
      scope: "Source labels only.",
    },
    spine: [
      { index: 0, idref: "chapter", path: "EPUB/one.xhtml", linear: "yes" },
    ],
    manifest: [
      {
        id: "chapter",
        path: "EPUB/one.xhtml",
        media_type: "application/xhtml+xml",
        properties: [],
      },
    ],
    documents: [{ path: "EPUB/one.xhtml", byte_sha256: resource }],
    content_evidence: {
      policy: "librarium.epub-content-evidence.v1",
      status: "recorded",
      source_sha256: sha,
      text_sha256: "c".repeat(64),
      spine_bytes_sha256: "d".repeat(64),
      text_chars: 123,
      spine_documents: 1,
      reason: null,
      scope: "Ordered XHTML body source text.",
    },
    document_text_evidence: {
      policy: "librarium.epub-document-text.v1",
      status: "recorded",
      source_sha256: sha,
      documents: [
        {
          path: "EPUB/one.xhtml",
          spine_index: 0,
          resource_sha256: resource,
          text_sha256: "c".repeat(64),
          text_chars: 123,
        },
      ],
      reason: null,
      scope: "Normalized document body source text only.",
    },
  };
}
function binds(report: any, version = report.policy.version) {
  const job = {
    id: "inspection",
    source_version: version,
    source_sha256: sha,
    result: { report_sha256: sha },
  } as Job;
  return reportBinds(job, {
    job_id: job.id,
    source_sha256: sha,
    report_sha256: sha,
    report,
  });
}
it("binds v8 document text observations and preserves unknown without rows", () => {
  const report = captured();
  expect(binds(report)).toBe(true);
  report.document_text_evidence = {
    ...report.document_text_evidence,
    status: "unconfirmed",
    documents: [],
    reason: "unsupported_spine_resource",
  };
  report.inspection_complete = false;
  report.structural_check = "failed";
  expect(binds(report)).toBe(true);
});
it.each([
  "source",
  "policy",
  "missing",
  "null",
  "status",
  "reason",
  "path",
  "index",
  "resource",
  "digest",
  "chars",
  "count",
  "duplicate",
  "failed",
  "partial",
  "budget",
  "media",
  "unknown_rows",
  "unknown_reason",
  "extra",
  "null_document",
  "null_manifest",
  "global_count",
  "global_chars",
  "global_missing",
  "global_source",
  "records",
])("refuses malformed document text evidence: %s", (field) => {
  const report = captured();
  const value = report.document_text_evidence;
  const row = value.documents[0];
  if (field === "source") value.source_sha256 = resource;
  if (field === "policy") value.policy = "unknown";
  if (field === "missing") delete report.document_text_evidence;
  if (field === "null") report.document_text_evidence = null;
  if (field === "status") value.status = "verified";
  if (field === "reason") value.reason = "partial";
  if (field === "path") row.path = "EPUB/other.xhtml";
  if (field === "index") row.spine_index = true;
  if (field === "resource") row.resource_sha256 = sha;
  if (field === "digest") row.text_sha256 = "x".repeat(64);
  if (field === "chars") row.text_chars = 0;
  if (field === "count") value.documents = [];
  if (field === "duplicate") value.documents.push({ ...row });
  if (field === "failed") report.structural_check = "failed";
  if (field === "partial") report.inspection_complete = false;
  if (field === "budget") report.policy.limits = { max_xml_text_chars: 122 };
  if (field === "media") report.manifest[0].media_type = "image/png";
  if (field === "unknown_rows") {
    value.status = "unconfirmed";
    value.reason = "unsupported";
  }
  if (field === "unknown_reason") {
    value.status = "unconfirmed";
    value.documents = [];
    value.reason = null;
  }
  if (field === "null_document") report.documents = [null];
  if (field === "null_manifest") report.manifest = [null];
  if (field === "global_count") report.content_evidence.spine_documents = 2;
  if (field === "global_chars") report.content_evidence.text_chars = 124;
  if (field === "global_missing") delete report.content_evidence;
  if (field === "global_source")
    report.content_evidence.source_sha256 = resource;
  if (field === "records") report.policy.limits = { max_records: 2 };
  if (field === "extra")
    row.text = "Source prose cannot be added to fingerprint rows.";
  expect(binds(report)).toBe(false);
});
it("does not assign new capture to historical policies or accept mixed job/report policies", () => {
  const report = captured();
  expect(binds(report, "librarium.epub-structure.v7")).toBe(false);
  report.policy.version = "librarium.epub-structure.v7";
  expect(binds(report)).toBe(false);
  delete report.document_text_evidence;
  expect(binds(report)).toBe(true);
});

it("binds multiple documents with the normalized separator accounted once", () => {
  const report = captured();
  report.spine.push({
    index: 1,
    idref: "two",
    path: "EPUB/two.xhtml",
    linear: "no",
  });
  report.manifest.push({
    id: "two",
    path: "EPUB/two.xhtml",
    media_type: "text/html",
    properties: [],
  });
  report.documents.push({ path: "EPUB/two.xhtml", byte_sha256: sha });
  report.document_text_evidence.documents.push({
    path: "EPUB/two.xhtml",
    spine_index: 1,
    resource_sha256: sha,
    text_sha256: "d".repeat(64),
    text_chars: 51,
  });
  report.content_evidence.spine_documents = 2;
  report.content_evidence.text_chars = 175;
  expect(binds(report)).toBe(true);
  report.content_evidence.text_chars = 174;
  expect(binds(report)).toBe(false);
});

it("includes document fingerprint rows in the captured record budget", () => {
  const report = captured();
  report.policy.limits = { max_records: 3 };
  expect(binds(report)).toBe(false);
  report.policy.limits.max_records = 4;
  expect(binds(report)).toBe(true);
});

it("allows unrelated manifest aliases while refusing ambiguous captured spine resources", () => {
  const report = captured();
  report.manifest.push(
    {
      id: "cover-a",
      path: "EPUB/cover.png",
      media_type: "image/png",
      properties: [],
    },
    {
      id: "cover-b",
      path: "EPUB/cover.png",
      media_type: "image/png",
      properties: [],
    },
  );
  expect(binds(report)).toBe(true);
  report.manifest.push({ ...report.manifest[0], id: "spine-alias" });
  expect(binds(report)).toBe(false);
});

it("bounds manifest aliases by records rather than unique archive member count", () => {
  const report = captured();
  report.policy.limits = { max_members: 1, max_records: 6 };
  report.manifest.push(
    {
      id: "cover-a",
      path: "EPUB/cover.png",
      media_type: "image/png",
      properties: [],
    },
    {
      id: "cover-b",
      path: "EPUB/cover.png",
      media_type: "image/png",
      properties: [],
    },
  );
  expect(binds(report)).toBe(true);
  report.policy.limits.max_records = 5;
  expect(binds(report)).toBe(false);
});

function withPicturePage(): any {
  // Inspection v10: a text-empty picture page is a zero-character row, counted once.
  const report = captured();
  report.policy.version = "librarium.epub-structure.v10";
  report.content_evidence.policy = "librarium.epub-content-evidence.v2";
  report.content_evidence.empty_spine_documents = 1;
  report.content_evidence.spine_documents = 2;
  report.document_text_evidence.policy = "librarium.epub-document-text.v2";
  report.spine.unshift({
    index: 0,
    idref: "plate",
    path: "EPUB/plate.xhtml",
    linear: "yes",
  });
  report.spine[1].index = 1;
  report.manifest.push({
    id: "plate",
    path: "EPUB/plate.xhtml",
    media_type: "application/xhtml+xml",
    properties: [],
  });
  report.documents.push({ path: "EPUB/plate.xhtml", byte_sha256: sha });
  report.document_text_evidence.documents[0].spine_index = 1;
  report.document_text_evidence.documents.unshift({
    path: "EPUB/plate.xhtml",
    spine_index: 0,
    resource_sha256: sha,
    text_sha256:
      "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855",
    text_chars: 0,
  });
  return report;
}

it("binds v10 text-empty picture pages without counting them as text", () => {
  expect(binds(withPicturePage())).toBe(true);
});

it.each(["digest", "count", "all_empty", "historical", "content_policy"])(
  "refuses v10 empty-page rows that disagree with their counts: %s",
  (change) => {
    const report = withPicturePage();
    const [plate, chapter] = report.document_text_evidence.documents;
    if (change === "digest") plate.text_sha256 = "c".repeat(64);
    if (change === "count") report.content_evidence.empty_spine_documents = 0;
    if (change === "all_empty") {
      chapter.text_chars = 0;
      chapter.text_sha256 = plate.text_sha256;
      report.content_evidence.empty_spine_documents = 2;
    }
    if (change === "historical")
      report.policy.version = "librarium.epub-structure.v9";
    if (change === "content_policy")
      report.content_evidence.policy = "librarium.epub-content-evidence.v1";
    expect(binds(report)).toBe(false);
  },
);
