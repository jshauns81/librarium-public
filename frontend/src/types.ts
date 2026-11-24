export type WorkRow = {
  id: string;
  title: string;
  author: string;
  series: string;
  edition_count: number;
  source_version: string;
};
export type Work = WorkRow & {
  synthetic: boolean;
  description: string;
  library_uuid: string;
  file_sha256: string;
  library_title: string;
  library_isbn: string;
  source_version: string;
  fault: string | null;
  editions: { id: string; format: string; isbn: string | null; year: number }[];
  evidence: {
    source: string;
    field: string;
    value: string;
    native_id: string;
    observed_at: string;
  }[];
};
export type JobKind =
  | "synthetic"
  | "catalogue"
  | "epub"
  | "epub_validation"
  | "library_reconcile"
  | "book_assessment"
  | "epub_correction"
  | "output_validation"
  | "delivery_prepare"
  | "epub_delivery"
  | "delivery_reconcile"
  | "epub_undo";
export type EpubValidatorProfile = {
  name: string;
  version: string;
  distribution_sha256: string;
  jar_manifest_sha256: string;
  java_major: number;
  [key: string]: unknown;
};
export type EpubValidationPolicy = { version: string; [key: string]: unknown };
export type EpubValidationCounts = {
  fatal: number;
  error: number;
  warning: number;
  info: number | null;
  usage: number;
};
export type EpubValidationReport = {
  schema_version: string;
  source_sha256: string;
  source_size: number;
  validator: EpubValidatorProfile;
  policy: EpubValidationPolicy;
  outcome: "passed" | "failed";
  counts: EpubValidationCounts;
  messages: {
    id: string;
    severity: "FATAL" | "ERROR" | "WARNING" | "INFO" | "USAGE";
    message: string;
    locations: { path: string; line: number | null; column: number | null }[];
  }[];
  messages_truncated: boolean;
  message_repetition_limit: number;
  process_exit_code: 0 | 1;
  ready: false;
  content_acceptance: "not_checked";
  limitations: string[];
};
export type EpubValidationEnvelope = {
  job_id: string;
  source_job_id: string;
  source_sha256: string;
  source_report_sha256: string;
  report_sha256: string;
  report: EpubValidationReport;
};
export type Finding = {
  name: string;
  ok: boolean;
  detail: string;
  status?: "pass" | "attention" | "partial" | "not_checked";
  items?: Record<string, unknown>[];
  missing?: string[];
};
export type Job = {
  kind?: JobKind;
  id: string;
  request_key: string;
  work_id: string;
  title: string;
  state: string;
  revision: number;
  checkpoint: number;
  attempts: number;
  message: string;
  updated_at: string;
  source_version: string;
  source_sha256?: string | null;
  source_job_id?: string;
  source_report_sha256?: string;
  catalogue_version?: string;
  catalogue_sha256?: string;
  catalogue_work_id?: string;
  reconciliation_key?: string;
  source_size?: number;
  validator?: EpubValidatorProfile;
  policy?: EpubValidationPolicy;
  input_fingerprint: string;
  result: {
    synthetic?: boolean;
    read_only?: boolean;
    ready?: boolean;
    epubcheck?: string;
    content_acceptance?: string;
    structural_check?: string;
    inspection_complete?: boolean;
    report_sha256?: string;
    report_size?: number;
    report_url?: string;
    findings?: Finding[];
    scope?: string;
    contents_plan?: EpubContentsPlanSummary;
    kind?: JobKind;
    input_fingerprint?: string;
    source_job_id?: string;
    source_report_sha256?: string;
    source_sha256?: string;
    source_size?: number;
    source_version?: string;
    validator?: EpubValidatorProfile;
    policy?: EpubValidationPolicy;
    outcome?: "passed" | "failed";
    counts?: EpubValidationCounts;
    messages_truncated?: boolean;
    message_repetition_limit?: number;
    process_exit_code?: 0 | 1;
    [key: string]: unknown;
  };
};
export type Session = {
  csrf: string;
  library?: boolean;
  direct_library?: boolean;
  file_inspections?: boolean;
  file_inspection_max_bytes?: number;
  epub_validation?: boolean;
  epub_validator?: { name: string; version: string; policy_version: string };
};
export type EpubContentsPlanEntry = {
  label: string;
  path: string;
  fragment: string | null;
  requires_anchor: boolean;
  origin: string;
  position: {
    document_index: number;
    source_index: number;
    word_offset: number;
    document_sha256: string;
  };
  label_source: {
    path: string;
    source_index: number;
    document_sha256: string;
  };
  children: EpubContentsPlanEntry[];
};
export type EpubContentsPlan = {
  policy_version: string;
  source_sha256: string;
  inspection_policy: string;
  decision: "keep" | "propose" | "held";
  reason_codes: string[];
  existing: {
    label: string;
    path: string;
    fragment: string | null;
    kind: string;
    ancestors: string[];
  }[];
  entries: EpubContentsPlanEntry[];
  excluded_targets: { path: string; fragment: string | null; reason: string }[];
  limitations: string[];
  /** Plan v2: the counts the contents rules decided on, and up to three findings. */
  measures?: {
    existing: number;
    headings: number;
    linked: number;
    entries: number;
    words: number;
  } | null;
  problems?: string[];
  ready: false;
};
export type EpubContentsPlanSummary = Pick<
  EpubContentsPlan,
  "policy_version" | "decision" | "reason_codes"
>;
export type IdentifierAssociation =
  "identifier" | "other" | "ambiguous" | "unresolved" | "unsupported";
export type IdentifierEvidence = {
  schema_version: string;
  package_path: string;
  package_sha256: string;
  package_version: string;
  unique_identifier: string | null;
  prefix: string | null;
  entries: {
    source_index: number;
    value: string;
    id: string | null;
    xml_id: string | null;
    opf_scheme: string | null;
    id_count: number;
    xml_id_count: number;
    text_only: boolean;
  }[];
  refinements: {
    source_index: number;
    property: string;
    refines: string | null;
    scheme: string | null;
    value: string;
    text_only: boolean;
    target_id: string | null;
    target_count: number;
    target_source_index: number | null;
    association: IdentifierAssociation;
  }[];
};
export type SourceAttribution = {
  policy: string;
  status: "recorded" | "unconfirmed";
  source_sha256: string | null;
  reason: string | null;
  scope: string;
  observations: {
    id: string;
    spine_index: number;
    path: string;
    resource_sha256: string;
    source_index: number;
    rule: "semantic_titlepage" | "front_matter_lead";
    scope: "container_candidate" | "unclassified";
    title: { text: string; source_index: number; marker: string } | null;
    credits: { text: string; source_index: number; marker: string }[];
  }[];
};
export type DocumentTextEvidence = {
  policy: "librarium.epub-document-text.v1" | "librarium.epub-document-text.v2";
  status: "recorded" | "unconfirmed";
  source_sha256: string;
  documents: {
    path: string;
    spine_index: number;
    resource_sha256: string;
    text_sha256: string;
    text_chars: number;
  }[];
  reason: string | null;
  scope: string;
};
export type EpubReport = {
  schema_version?: string;
  source_sha256?: string;
  expected_sha256?: string;
  policy?: { version?: string; limits?: Record<string, number> };
  upstream?: {
    repository?: string;
    revision?: string;
    source?: string;
    source_sha256?: string;
  };
  archive?: { member_count?: number; expanded_bytes?: number } | null;
  package?: { path?: string; version?: string; byte_sha256?: string } | null;
  identifier_evidence?: IdentifierEvidence | null;
  source_attribution?: SourceAttribution | null;
  document_text_evidence?: DocumentTextEvidence | null;
  content_evidence?: {
    policy: string;
    status: "recorded" | "unconfirmed";
    source_sha256: string;
    text_sha256: string | null;
    spine_bytes_sha256: string | null;
    text_chars: number | null;
    spine_documents: number | null;
    /** Content evidence v2: text-empty spine pages, such as image-only pages. */
    empty_spine_documents?: number | null;
    reason: string | null;
    scope: string;
  } | null;
  metadata?: { name: string; text: string }[];
  manifest?: {
    id: string;
    path: string;
    media_type: string;
    properties: string[];
  }[];
  spine?: { index: number; idref: string; path: string; linear: string }[];
  documents?: {
    path: string;
    byte_sha256?: string;
    source_element_count?: number;
    headings?: {
      level: number;
      id?: string | null;
      chapter_number?: number | null;
      label?: string;
    }[];
    links?: {
      tag: string;
      attribute: string;
      target_path: string | null;
      fragment: string | null;
      external: boolean;
      heading_index?: number | null;
      label?: string;
    }[];
  }[];
  navigation?: {
    nav_paths?: string[];
    ncx_paths?: string[];
    entries?: {
      path: string;
      target_path: string;
      fragment: string | null;
      label?: string;
      kind?: "nav" | "ncx";
      ancestors?: string[];
    }[];
    external_link_count?: number;
  };
  findings?: { code: string; severity: string; path?: string }[];
  findings_truncated?: boolean;
  inspection_complete?: boolean;
  structural_check?: string;
  epubcheck?: string;
  content_acceptance?: string;
  ready?: boolean;
  contents_plan?: EpubContentsPlan | null;
};
export type EpubReportEnvelope = {
  job_id: string;
  source_sha256: string;
  report_sha256: string;
  report: EpubReport;
};
export type Collection = {
  works: WorkRow[];
  total: number;
  page: number;
  page_size: number;
  source_versions: string[];
};
export type JobHistory = {
  jobs: Job[];
  total: number;
  page: number;
  page_size: number;
};
