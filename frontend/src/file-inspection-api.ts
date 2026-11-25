import { api, ApiError } from "./api";
import type { EpubReport, EpubReportEnvelope, Job } from "./types";

// The shared api() helper bounds reads at 5 s. A 32 MiB upload needs its own
// deadline, so uploads and report reads use this same-origin request instead.
export const UPLOAD_DEADLINE_MS = 120_000;
export const REPORT_DEADLINE_MS = 20_000;
export const DEFAULT_MAX_BYTES = 32 * 1024 * 1024;
export const INTENT_STORAGE = "librarium-file-intent";
const UUID = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
const DIGEST = /^[a-f0-9]{64}$/;

export type FileIntent = {
  key: string;
  digest: string;
  name: string;
  size: number;
};

type IntentStorage = Pick<Storage, "getItem" | "setItem" | "removeItem">;

export function readIntent(storage: IntentStorage): FileIntent | null {
  try {
    const value = JSON.parse(storage.getItem(INTENT_STORAGE) ?? "null");
    if (
      value &&
      typeof value === "object" &&
      UUID.test(value.key) &&
      DIGEST.test(value.digest) &&
      typeof value.name === "string" &&
      Number.isSafeInteger(value.size) &&
      value.size >= 0
    )
      return {
        key: value.key,
        digest: value.digest,
        name: value.name,
        size: value.size,
      };
  } catch {
    // Unreadable intent metadata is treated as absent.
  }
  return null;
}

export function writeIntent(storage: IntentStorage, intent: FileIntent) {
  storage.setItem(INTENT_STORAGE, JSON.stringify(intent));
}

export function clearIntent(storage: IntentStorage, key?: string) {
  if (!key || readIntent(storage)?.key === key)
    storage.removeItem(INTENT_STORAGE);
}

export function sourceName(name: string): string {
  const cleaned = Array.from(name)
    .filter((char) => !/[\p{C}/\\]/u.test(char))
    .join("")
    .trim()
    .slice(0, 240)
    .trim();
  return cleaned || "Uploaded EPUB.epub";
}

export async function digestBytes(buffer: ArrayBuffer): Promise<string> {
  const hash = await crypto.subtle.digest("SHA-256", buffer);
  return Array.from(new Uint8Array(hash), (byte) =>
    byte.toString(16).padStart(2, "0"),
  ).join("");
}

export function formatBytes(size: number): string {
  const exact = `${size.toLocaleString()} bytes`;
  return size >= 1024 * 1024
    ? `${(size / (1024 * 1024)).toFixed(1)} MiB (${exact})`
    : exact;
}

async function request<T>(
  path: string,
  init: RequestInit,
  deadline: number,
): Promise<T> {
  const response = await fetch(`/api/${path}`, {
    ...init,
    signal: AbortSignal.any([
      ...(init.signal ? [init.signal] : []),
      AbortSignal.timeout(deadline),
    ]),
  });
  if (!response.ok) {
    const body = await response
      .json()
      .catch(() => ({ error: `Request failed (${response.status})` }));
    throw new ApiError(
      body.error || `Request failed (${response.status})`,
      response.status,
    );
  }
  return response.json() as Promise<T>;
}

export function uploadEpub({
  csrf,
  intent,
  body,
  signal,
}: {
  csrf: string;
  intent: FileIntent;
  body: ArrayBuffer;
  signal?: AbortSignal;
}): Promise<Job> {
  return request<Job>(
    "epub-inspections",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/epub+zip",
        "X-CSRFToken": csrf,
        "Idempotency-Key": intent.key,
        "X-Source-SHA256": intent.digest,
        "X-Source-Name": encodeURIComponent(intent.name),
      },
      body,
      signal,
    },
    UPLOAD_DEADLINE_MS,
  );
}

export function lookupInspection(key: string, signal?: AbortSignal) {
  return api<Job>(`epub-inspections?request_key=${encodeURIComponent(key)}`, {
    signal,
  });
}

export function fetchReport(jobId: string, signal?: AbortSignal) {
  return request<EpubReportEnvelope>(
    `epub-inspections/${encodeURIComponent(jobId)}/report`,
    { signal },
    REPORT_DEADLINE_MS,
  );
}

// A report is shown only when every binding it carries matches the job that
// asked for it; anything else is refused rather than displayed.
export function reportBinds(job: Job, envelope: EpubReportEnvelope): boolean {
  const report = envelope.report;
  return (
    !!report &&
    typeof report === "object" &&
    (job.source_version
      ? job.source_version === report.policy?.version
      : !capturesIdentifierEvidence(report.policy?.version)) &&
    identifierEvidenceBinds(report) &&
    sourceAttributionBinds(report) &&
    documentTextEvidenceBinds(report) &&
    envelope.job_id === job.id &&
    !!job.source_sha256 &&
    envelope.source_sha256 === job.source_sha256 &&
    report.source_sha256 === job.source_sha256 &&
    (!job.result.report_sha256 ||
      envelope.report_sha256 === job.result.report_sha256)
  );
}

const object = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

export function capturesIdentifierEvidence(
  version: string | undefined,
): boolean {
  return (
    version === "librarium.epub-structure.v5" ||
    version === "librarium.epub-structure.v6" ||
    version === "librarium.epub-structure.v7" ||
    version === "librarium.epub-structure.v8" ||
    version === "librarium.epub-structure.v9" ||
    version === "librarium.epub-structure.v10" ||
    version === "librarium.epub-structure.v11"
  );
}

export function identifierEvidenceBinds(report: EpubReport): boolean {
  if (!capturesIdentifierEvidence(report.policy?.version)) return true;
  const evidence: unknown = report.identifier_evidence;
  if (evidence == null) return report.inspection_complete === false;
  const limits = report.policy?.limits ?? {};
  function limit(name: string, maximum: number) {
    const value = limits[name];
    return value === undefined
      ? maximum
      : Number.isInteger(value) && value > 0 && value <= maximum
        ? value
        : 0;
  }
  const textLimit = limit("max_metadata_chars", 256),
    fieldLimit = limit("max_field_chars", 512),
    recordLimit = limit("max_records", 8192),
    nodeLimit = limit("max_xml_nodes", 100000);
  const text = (value: unknown, max = fieldLimit): value is string =>
    typeof value === "string" && Array.from(value).length <= max;
  const nullable = (value: unknown) => value === null || text(value);
  const index = (value: unknown, minimum = 2): value is number =>
    Number.isInteger(value) &&
    (value as number) >= minimum &&
    (value as number) < nodeLimit;
  const count = (value: unknown) =>
    Number.isInteger(value) &&
    (value as number) >= 0 &&
    (value as number) <= nodeLimit;
  if (
    !textLimit ||
    !fieldLimit ||
    !recordLimit ||
    !nodeLimit ||
    !object(evidence) ||
    evidence.schema_version !== "librarium.epub-identifiers.v1" ||
    !text(evidence.package_path) ||
    !text(evidence.package_version) ||
    typeof evidence.package_sha256 !== "string" ||
    !DIGEST.test(evidence.package_sha256) ||
    evidence.package_path !== report.package?.path ||
    evidence.package_version !== report.package?.version ||
    evidence.package_sha256 !== report.package?.byte_sha256 ||
    !nullable(evidence.unique_identifier) ||
    !nullable(evidence.prefix) ||
    !Array.isArray(evidence.entries) ||
    !Array.isArray(evidence.refinements) ||
    evidence.entries.length + evidence.refinements.length > recordLimit
  )
    return false;
  const seen = new Set<number>();
  let previous = -1;
  if (
    !evidence.entries.every((entry) => {
      if (
        !object(entry) ||
        !index(entry.source_index) ||
        entry.source_index <= previous ||
        seen.has(entry.source_index) ||
        !text(entry.value, textLimit) ||
        !nullable(entry.id) ||
        !nullable(entry.xml_id) ||
        !nullable(entry.opf_scheme) ||
        !count(entry.id_count) ||
        !count(entry.xml_id_count) ||
        typeof entry.text_only !== "boolean"
      )
        return false;
      previous = entry.source_index;
      seen.add(entry.source_index);
      return true;
    })
  )
    return false;
  previous = -1;
  if (
    !evidence.refinements.every((entry) => {
      if (
        !object(entry) ||
        !index(entry.source_index) ||
        entry.source_index <= previous ||
        seen.has(entry.source_index) ||
        !text(entry.property) ||
        !nullable(entry.refines) ||
        !nullable(entry.scheme) ||
        !text(entry.value, textLimit) ||
        typeof entry.text_only !== "boolean" ||
        !nullable(entry.target_id) ||
        !count(entry.target_count) ||
        !(
          entry.target_source_index === null ||
          index(entry.target_source_index, 0)
        ) ||
        ![
          "identifier",
          "other",
          "ambiguous",
          "unresolved",
          "unsupported",
        ].includes(entry.association as string)
      )
        return false;
      previous = entry.source_index;
      seen.add(entry.source_index);
      return true;
    })
  )
    return false;
  if (
    !Array.isArray(report.metadata) ||
    !report.metadata.every(
      (entry) =>
        object(entry) &&
        typeof entry.name === "string" &&
        typeof entry.text === "string",
    )
  )
    return false;
  const values = report.metadata
    .filter((entry) => entry.name === "identifier")
    .map((entry) => entry.text);
  const recordedEntries = evidence.entries;
  return (
    values.length === recordedEntries.length &&
    values.every((value, i) => value === recordedEntries[i].value)
  );
}

const FINDING_NOTES: Record<string, string> = {
  source_hash_mismatch: "The preserved bytes do not match the recorded digest.",
  invalid_zip: "The file is not a readable ZIP archive.",
  zip_crc_failure: "A compressed member failed its CRC check.",
  invalid_xml: "An XML document could not be parsed.",
  invalid_container: "META-INF/container.xml is not an OCF container.",
  missing_package_rootfile: "The container names no package document.",
  multiple_renditions_not_supported: "Only a single rendition is inspected.",
  unsafe_package_reference: "A package reference escapes the archive.",
  unsupported_package: "The package version is not EPUB 2.0 or 3.0.",
  empty_manifest: "The manifest lists no items.",
  duplicate_manifest_id: "Two manifest items share one identifier.",
  missing_manifest_id: "A manifest item has no identifier.",
  missing_manifest_resource: "A manifest item points to a missing member.",
  missing_navigation: "No navigation document or NCX was declared.",
  empty_navigation:
    "This book has no usable table of contents: its navigation lists no entries.",
  unreadable_navigation: "The navigation document could not be read.",
  invalid_navigation_target: "A navigation entry points outside the archive.",
  empty_spine: "The spine lists no reading order.",
  missing_spine_manifest_id: "A spine item names an unknown manifest id.",
  unreadable_spine_document: "A spine item is not a readable document.",
  repeated_spine_document: "The same document appears twice in the spine.",
  invalid_spine_linear: "A spine item has an invalid linear value.",
  missing_link_resource: "A link targets a member that does not exist.",
  missing_link_fragment: "A link targets a fragment that does not exist.",
  uncheckable_fragment_target: "A fragment target could not be checked.",
  duplicate_document_id: "A document reuses an element id.",
  unsafe_resource_link: "A resource link escapes the archive.",
  remote_resource_reference: "A resource is loaded from outside the file.",
  unexpected_document_root: "A document has an unexpected root element.",
  output_bytes_limit: "The report exceeded its size budget and was reduced.",
  archive_bytes_limit: "The archive exceeds the inspection size budget.",
  record_limit: "The inspection stopped at its record budget.",
  field_limit: "A field exceeded its length budget.",
  finding_limit: "The findings list reached its budget.",
  metadata_limit: "A metadata value exceeded its length budget.",
};

export function describeFinding(code: string): {
  label: string;
  note: string;
} {
  const label = code
    ? code.charAt(0).toUpperCase() + code.slice(1).replace(/_/g, " ")
    : "Unnamed finding";
  return { label, note: FINDING_NOTES[code] ?? "" };
}

export function sourceAttributionBinds(report: EpubReport): boolean {
  const value = report.source_attribution;
  if (!capturesSourceAttribution(report.policy?.version)) return value == null;
  if (
    !value ||
    value.policy !== "librarium.epub-source-attribution.v1" ||
    typeof value.source_sha256 !== "string" ||
    !DIGEST.test(value.source_sha256) ||
    value.source_sha256 !== report.source_sha256 ||
    typeof value.scope !== "string" ||
    !Array.isArray(value.observations) ||
    value.observations.length > 8
  )
    return false;
  if (value.status === "unconfirmed")
    return (
      typeof value.reason === "string" &&
      /^[a-z_]{1,80}$/.test(value.reason) &&
      value.observations.length === 0
    );
  if (
    value.status !== "recorded" ||
    value.reason !== null ||
    !value.observations.length ||
    report.inspection_complete !== true ||
    report.structural_check !== "passed"
  )
    return false;
  const ids = new Set<string>();
  let previousSpine = -1,
    previousIndex = -1;
  return value.observations.every((entry, ordinal) => {
    if (!object(entry)) return false;
    const doc = report.documents?.filter((d) => d.path === entry.path);
    const spine = report.spine?.[entry.spine_index];
    const nodeCount = doc?.[0]?.source_element_count;
    const index = (n: number) =>
      Number.isInteger(n) &&
      n >= 0 &&
      typeof nodeCount === "number" &&
      Number.isInteger(nodeCount) &&
      nodeCount > 0 &&
      nodeCount <= 100000 &&
      n < nodeCount;
    const label = (v: { text: string; source_index: number; marker: string }) =>
      !!v &&
      typeof v.text === "string" &&
      Array.from(v.text).length > 0 &&
      Array.from(v.text).length <=
        Math.min(256, report.policy?.limits?.max_metadata_chars ?? 256) &&
      index(v.source_index) &&
      v.source_index >= entry.source_index &&
      typeof v.marker === "string" &&
      v.marker.length <= 64;
    if (
      entry.id !== `source-title-${ordinal + 1}` ||
      ids.has(entry.id) ||
      !Number.isInteger(entry.spine_index) ||
      entry.spine_index < 0 ||
      entry.spine_index >= 4 ||
      !spine ||
      spine.linear !== "yes" ||
      report.navigation?.nav_paths?.includes(entry.path) ||
      spine.path !== entry.path ||
      doc?.length !== 1 ||
      !DIGEST.test(entry.resource_sha256) ||
      doc[0].byte_sha256 !== entry.resource_sha256 ||
      !index(entry.source_index) ||
      entry.spine_index < previousSpine ||
      (entry.spine_index === previousSpine &&
        entry.source_index <= previousIndex) ||
      !["semantic_titlepage", "front_matter_lead"].includes(entry.rule) ||
      entry.scope !==
        (entry.rule === "semantic_titlepage"
          ? "container_candidate"
          : "unclassified") ||
      (entry.title !== null && !label(entry.title)) ||
      !Array.isArray(entry.credits) ||
      entry.credits.length > 16 ||
      !entry.credits.every(label) ||
      (entry.title === null && !entry.credits.length)
    )
      return false;
    const titleMarkers = ["title", "fulltitle", "doc-title"];
    const creditMarkers = ["author", "docauthor", "doc-author", "z3998:author"];
    const labels = [...(entry.title ? [entry.title] : []), ...entry.credits];
    if (
      new Set(labels.map((v) => v.source_index)).size !== labels.length ||
      entry.credits.some((v) => !creditMarkers.includes(v.marker)) ||
      (entry.rule === "semantic_titlepage" &&
        entry.title &&
        !titleMarkers.includes(entry.title.marker)) ||
      (entry.rule === "front_matter_lead" &&
        (!entry.title ||
          entry.credits.length ||
          entry.title.marker !== "heading" ||
          entry.title.source_index !== entry.source_index))
    )
      return false;
    ids.add(entry.id);
    previousSpine = entry.spine_index;
    previousIndex = entry.source_index;
    return true;
  });
}

export function capturesSourceAttribution(
  version: string | undefined,
): boolean {
  return (
    version === "librarium.epub-structure.v7" ||
    version === "librarium.epub-structure.v8" ||
    version === "librarium.epub-structure.v9" ||
    version === "librarium.epub-structure.v10" ||
    version === "librarium.epub-structure.v11"
  );
}

// Inspection v10 and v11 record text-empty spine pages (image-only or blank) as zero-character
// rows under document-text v2 and counts them in content-evidence v2.
const EMPTY_TEXT_SHA256 =
  "e3b0c44298fc1c149afbf4c8996fb92427ae41e4649b934ca495991b7852b855";
const DOCUMENT_TEXT_POLICIES: Record<string, [string, string]> = {
  "librarium.epub-structure.v8": [
    "librarium.epub-document-text.v1",
    "librarium.epub-content-evidence.v1",
  ],
  "librarium.epub-structure.v9": [
    "librarium.epub-document-text.v1",
    "librarium.epub-content-evidence.v1",
  ],
  "librarium.epub-structure.v10": [
    "librarium.epub-document-text.v2",
    "librarium.epub-content-evidence.v2",
  ],
  "librarium.epub-structure.v11": [
    "librarium.epub-document-text.v2",
    "librarium.epub-content-evidence.v2",
  ],
};

export function documentTextEvidenceBinds(report: EpubReport): boolean {
  const value: unknown = report.document_text_evidence;
  const version = report.policy?.version ?? "";
  if (!Object.hasOwn(DOCUMENT_TEXT_POLICIES, version)) return value == null;
  const [textPolicy, contentPolicy] = DOCUMENT_TEXT_POLICIES[version];
  const emptyRows = textPolicy === "librarium.epub-document-text.v2";
  const keys = (entry: Record<string, unknown>, names: string[]) =>
    Object.keys(entry).length === names.length &&
    names.every((key) => Object.hasOwn(entry, key));
  if (
    !object(value) ||
    !keys(value, [
      "policy",
      "status",
      "source_sha256",
      "documents",
      "reason",
      "scope",
    ]) ||
    value.policy !== textPolicy ||
    typeof value.source_sha256 !== "string" ||
    !DIGEST.test(value.source_sha256) ||
    value.source_sha256 !== report.source_sha256 ||
    typeof value.scope !== "string" ||
    !value.scope.length ||
    value.scope.length > 2048 ||
    !Array.isArray(value.documents)
  )
    return false;
  if (value.status === "unconfirmed")
    return (
      value.documents.length === 0 &&
      typeof value.reason === "string" &&
      /^[a-z_]{1,80}$/.test(value.reason)
    );
  const limits = report.policy?.limits ?? {};
  function limit(name: string, maximum: number) {
    const captured = limits[name];
    return captured === undefined
      ? maximum
      : Number.isInteger(captured) && captured > 0 && captured <= maximum
        ? captured
        : 0;
  }
  const members = limit("max_members", 2048),
    records = limit("max_records", 8192),
    textLimit = limit("max_xml_text_chars", 16 * 1024 * 1024),
    nameLimit = limit("max_name_chars", 512);
  const spine = report.spine;
  const content = report.content_evidence;
  if (
    value.status !== "recorded" ||
    value.reason !== null ||
    report.inspection_complete !== true ||
    report.structural_check !== "passed" ||
    !members ||
    !records ||
    !textLimit ||
    !nameLimit ||
    !Array.isArray(spine) ||
    !spine.length ||
    spine.length > members ||
    value.documents.length !== spine.length ||
    !Array.isArray(report.documents) ||
    report.documents.length > members ||
    !Array.isArray(report.manifest) ||
    value.documents.length +
      spine.length +
      report.documents.length +
      report.manifest.length >
      records ||
    !object(content) ||
    content.policy !== contentPolicy ||
    content.status !== "recorded" ||
    content.source_sha256 !== report.source_sha256 ||
    content.spine_documents !== spine.length
  )
    return false;
  const paths = new Set<string>();
  let total = 0;
  let texts = 0;
  const valid = value.documents.every((row, ordinal) => {
    if (
      !object(row) ||
      !keys(row, [
        "path",
        "spine_index",
        "resource_sha256",
        "text_sha256",
        "text_chars",
      ]) ||
      typeof row.path !== "string" ||
      !row.path.length ||
      Array.from(row.path).length > nameLimit ||
      row.path.includes("\\") ||
      /[\u0000-\u001f\ud800-\udfff]/u.test(row.path) ||
      row.path.split("/").some((part) => ["", ".", ".."].includes(part)) ||
      paths.has(row.path) ||
      row.spine_index !== ordinal ||
      spine[ordinal]?.index !== ordinal ||
      spine[ordinal]?.path !== row.path ||
      typeof row.resource_sha256 !== "string" ||
      !DIGEST.test(row.resource_sha256) ||
      typeof row.text_sha256 !== "string" ||
      !DIGEST.test(row.text_sha256) ||
      !Number.isInteger(row.text_chars) ||
      (row.text_chars as number) < (emptyRows ? 0 : 1) ||
      (row.text_chars as number) > textLimit ||
      (row.text_chars === 0 && row.text_sha256 !== EMPTY_TEXT_SHA256)
    )
      return false;
    const documents = report.documents!.filter(
      (entry) => object(entry) && entry.path === row.path,
    );
    const manifest = report.manifest!.filter(
      (entry) => object(entry) && entry.path === row.path,
    );
    if (
      documents.length !== 1 ||
      documents[0].byte_sha256 !== row.resource_sha256 ||
      manifest.length !== 1 ||
      !["application/xhtml+xml", "text/html"].includes(manifest[0].media_type)
    )
      return false;
    paths.add(row.path);
    total += row.text_chars as number;
    texts += row.text_chars ? 1 : 0;
    return total <= textLimit;
  });
  return (
    valid &&
    texts > 0 &&
    total + texts - 1 <= textLimit &&
    total + texts - 1 === content.text_chars &&
    (!emptyRows ||
      content.empty_spine_documents === value.documents.length - texts)
  );
}
