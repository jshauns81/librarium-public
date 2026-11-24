import { api } from "./api";
import type {
  EpubValidationCounts,
  EpubValidationEnvelope,
  EpubValidationPolicy,
  EpubValidatorProfile,
  Job,
} from "./types";

const VALIDATION_REPORT_SCHEMA = "librarium.epub-validation.v1";
const digest = (value: unknown): value is string =>
  typeof value === "string" && /^[a-f0-9]{64}$/.test(value);
const natural = (value: unknown): value is number =>
  Number.isSafeInteger(value) && (value as number) >= 0;
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);

function canonical(value: unknown): string {
  if (Array.isArray(value)) return `[${value.map(canonical).join(",")}]`;
  if (record(value))
    return `{${Object.keys(value)
      .sort()
      .map((key) => `${JSON.stringify(key)}:${canonical(value[key])}`)
      .join(",")}}`;
  return JSON.stringify(value) ?? "undefined";
}
export const sameProfile = (left: unknown, right: unknown) =>
  canonical(left) === canonical(right);

function validValidator(value: unknown): value is EpubValidatorProfile {
  return (
    record(value) &&
    value.name === "EPUBCheck" &&
    typeof value.version === "string" &&
    !!value.version &&
    digest(value.distribution_sha256) &&
    digest(value.jar_manifest_sha256) &&
    natural(value.java_major) &&
    value.java_major > 0
  );
}
function validPolicy(value: unknown): value is EpubValidationPolicy {
  return (
    record(value) &&
    (value.version === "librarium.epub-validation.v1" ||
      value.version === "librarium.epub-validation.v2")
  );
}
export function validCounts(value: unknown): value is EpubValidationCounts {
  return (
    record(value) &&
    ["fatal", "error", "warning", "usage"].every((name) =>
      natural(value[name]),
    ) &&
    (value.info === null || natural(value.info))
  );
}

export function validationJobBinds(source: Job, job: Job): boolean {
  return (
    source.kind === "epub" &&
    source.state === "succeeded" &&
    digest(source.source_sha256) &&
    digest(source.result.report_sha256) &&
    job.kind === "epub_validation" &&
    !!job.id &&
    ["queued", "running", "succeeded", "failed", "cancelled"].includes(
      job.state,
    ) &&
    job.source_job_id === source.id &&
    job.source_report_sha256 === source.result.report_sha256 &&
    job.source_sha256 === source.source_sha256 &&
    job.work_id === source.source_sha256 &&
    natural(job.source_size) &&
    validValidator(job.validator) &&
    validPolicy(job.policy) &&
    job.source_version === job.policy.version
  );
}

export function validationSummaryBinds(source: Job, job: Job): boolean {
  const result = job.result;
  return (
    validationJobBinds(source, job) &&
    job.state === "succeeded" &&
    result.kind === "epub_validation" &&
    result.read_only === true &&
    result.synthetic === false &&
    result.input_fingerprint === job.input_fingerprint &&
    result.source_job_id === source.id &&
    result.source_report_sha256 === source.result.report_sha256 &&
    result.source_sha256 === source.source_sha256 &&
    result.source_size === job.source_size &&
    result.source_version === job.source_version &&
    sameProfile(result.policy, job.policy) &&
    sameProfile(result.validator, job.validator) &&
    ["passed", "failed"].includes(result.outcome ?? "") &&
    validCounts(result.counts) &&
    digest(result.report_sha256) &&
    typeof result.messages_truncated === "boolean" &&
    natural(result.message_repetition_limit) &&
    result.message_repetition_limit > 0 &&
    [0, 1].includes(result.process_exit_code ?? -1) &&
    result.ready === false &&
    result.content_acceptance === "not_checked" &&
    (result.outcome !== "passed" ||
      (result.counts.fatal === 0 &&
        result.counts.error === 0 &&
        result.process_exit_code === 0))
  );
}

export function validationReportBinds(
  source: Job,
  job: Job,
  envelope: EpubValidationEnvelope,
): boolean {
  const report = envelope?.report;
  return (
    validationSummaryBinds(source, job) &&
    record(report) &&
    envelope.job_id === job.id &&
    envelope.source_job_id === source.id &&
    envelope.source_sha256 === source.source_sha256 &&
    envelope.source_report_sha256 === source.result.report_sha256 &&
    envelope.report_sha256 === job.result.report_sha256 &&
    report.schema_version === VALIDATION_REPORT_SCHEMA &&
    report.source_sha256 === source.source_sha256 &&
    report.source_size === job.source_size &&
    sameProfile(report.validator, job.validator) &&
    sameProfile(report.policy, job.policy) &&
    report.outcome === job.result.outcome &&
    sameProfile(report.counts, job.result.counts) &&
    report.messages_truncated === job.result.messages_truncated &&
    report.message_repetition_limit === job.result.message_repetition_limit &&
    report.process_exit_code === job.result.process_exit_code &&
    report.ready === false &&
    report.content_acceptance === "not_checked" &&
    Array.isArray(report.limitations) &&
    report.limitations.every((value) => typeof value === "string") &&
    Array.isArray(report.messages) &&
    report.messages.every(
      (message) =>
        record(message) &&
        typeof message.id === "string" &&
        ["FATAL", "ERROR", "WARNING", "INFO", "USAGE"].includes(
          message.severity as string,
        ) &&
        typeof message.message === "string" &&
        Array.isArray(message.locations) &&
        message.locations.every(
          (location) =>
            record(location) &&
            typeof location.path === "string" &&
            (location.line === null ||
              (natural(location.line) && location.line > 0)) &&
            (location.column === null ||
              (natural(location.column) && location.column > 0)),
        ),
    )
  );
}

export type ValidationIntent = {
  key: string;
  source_job_id: string;
  source_sha256: string;
  source_report_sha256: string;
};
export const validationIntentKey = (sourceId: string) =>
  `librarium-epub-validation:${sourceId}`;
export function makeValidationIntent(source: Job): ValidationIntent {
  return {
    key: crypto.randomUUID(),
    source_job_id: source.id,
    source_sha256: source.source_sha256!,
    source_report_sha256: source.result.report_sha256!,
  };
}
export function readValidationIntent(source: Job): ValidationIntent | null {
  try {
    const value: unknown = JSON.parse(
      localStorage.getItem(validationIntentKey(source.id)) ?? "null",
    );
    if (
      record(value) &&
      typeof value.key === "string" &&
      /^[a-f0-9]{8}-[a-f0-9]{4}-4[a-f0-9]{3}-[89ab][a-f0-9]{3}-[a-f0-9]{12}$/.test(
        value.key,
      ) &&
      value.source_job_id === source.id &&
      value.source_sha256 === source.source_sha256 &&
      value.source_report_sha256 === source.result.report_sha256
    )
      return value as ValidationIntent;
  } catch {
    /* Storage may be unavailable in this browser. */
  }
  return null;
}
export function saveValidationIntent(intent: ValidationIntent): boolean {
  try {
    localStorage.setItem(
      validationIntentKey(intent.source_job_id),
      JSON.stringify(intent),
    );
    return true;
  } catch {
    return false;
  }
}
export function clearValidationIntent(source: Job, key: string) {
  const previous = readValidationIntent(source);
  if (previous?.key !== key) return;
  try {
    localStorage.removeItem(validationIntentKey(source.id));
  } catch {
    /* Retain the in-memory state. */
  }
}

export async function requestValidation(
  source: Job,
  key: string,
  csrf: string,
  signal: AbortSignal,
) {
  const job = await api<Job>(
    `epub-inspections/${encodeURIComponent(source.id)}/validations`,
    {
      method: "POST",
      headers: { "X-CSRFToken": csrf, "Idempotency-Key": key },
      body: "{}",
      signal,
    },
  );
  if (!validationJobBinds(source, job) || job.request_key !== key)
    throw new Error(
      "The returned EPUBCheck did not match this preserved source and request.",
    );
  return job;
}
export async function recoverValidation(
  source: Job,
  key: string,
  signal: AbortSignal,
) {
  const job = await api<Job>(
    `epub-inspections/${encodeURIComponent(source.id)}/validations?request_key=${encodeURIComponent(key)}`,
    { signal },
  );
  if (!validationJobBinds(source, job) || job.request_key !== key)
    throw new Error(
      "The recovered EPUBCheck did not match this preserved source and request.",
    );
  return job;
}
export async function readValidation(
  source: Job,
  id: string,
  signal: AbortSignal,
) {
  const job = await api<Job>(`jobs/${encodeURIComponent(id)}`, { signal });
  if (job.id !== id || !validationJobBinds(source, job))
    throw new Error(
      "The selected EPUBCheck does not match this preserved source.",
    );
  return job;
}
export async function readValidationHistory(
  source: Job,
  page: number,
  signal: AbortSignal,
) {
  const value = await api<{
    jobs: Job[];
    total: number;
    page: number;
    page_size: number;
  }>(
    `epub-inspections/${encodeURIComponent(source.id)}/validations?page=${page}`,
    { signal },
  );
  if (
    !Array.isArray(value.jobs) ||
    !value.jobs.every((job) => validationJobBinds(source, job)) ||
    !natural(value.total) ||
    value.page !== page ||
    value.page_size !== 20 ||
    value.jobs.length > 20
  )
    throw new Error(
      "The EPUBCheck history did not match this preserved source.",
    );
  return value;
}
export async function readValidationReport(
  source: Job,
  job: Job,
  signal: AbortSignal,
) {
  const envelope = await api<EpubValidationEnvelope>(
    `epub-validations/${encodeURIComponent(job.id)}/report`,
    { signal },
  );
  if (!validationReportBinds(source, job, envelope))
    throw new Error(
      "The EPUBCheck diagnostics do not match this job, preserved source and captured validator policy.",
    );
  return envelope;
}
