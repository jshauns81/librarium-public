import React from "react";
import type { Job } from "./types";
import { FindingEvidence } from "./FindingEvidence";
import { isRetiredKind, retiredKindLabel } from "./retired-kinds";
export const stateLabel: Record<string, string> = {
  queued: "Queued",
  running: "Comparing",
  succeeded: "Complete",
  failed: "Failed",
  cancelled: "Cancelled",
};

const HISTORICALLY_UNRECORDED = "Not recorded by this historical check";
// Old review-copy and delivery jobs are kept as plain past records: no report,
// no progress claims and no controls.
const retiredStateLabel: Record<string, string> = {
  ...stateLabel,
  running: "Running",
};
function RetiredJob({ job }: { job: Job }) {
  return (
    <div className="job-progress retired-job">
      <p className={`state state-${job.state}`}>
        <strong>{retiredStateLabel[job.state] ?? job.state}</strong>
      </p>
      {!!job.message.trim() && <p>{job.message}</p>}
      <p className="context-note">
        {retiredKindLabel(job.kind)} record from a retired feature. Librarium no
        longer makes review copies or delivers them.
      </p>
    </div>
  );
}

export function JobProgress({
  job,
  announce = false,
  findingsLevel = 4,
}: {
  job: Job;
  announce?: boolean;
  findingsLevel?: 3 | 4;
}) {
  if (isRetiredKind(job.kind)) return <RetiredJob job={job} />;
  const FindingHeading = findingsLevel === 3 ? "h3" : "h4";
  const epub = job.kind === "epub";
  const validation = job.kind === "epub_validation";
  const assessment = job.kind === "book_assessment";
  const libraryCheck = assessment || job.kind === "library_reconcile";
  const file = epub || validation || assessment;
  const indeterminate = validation || libraryCheck;
  const progressNoun = validation
    ? "EPUBCheck"
    : libraryCheck
      ? "Check"
      : job.kind === "catalogue"
        ? "Review"
        : "Inspection";
  const catalogueVersion = job.catalogue_version || job.source_version;
  const catalogueDigest =
    job.catalogue_sha256 ||
    (job.kind === "library_reconcile" ? job.source_sha256 : undefined);
  const scopeInFindings = job.result.findings?.some(
    (finding) => finding.detail === job.result.scope,
  );
  return (
    <div className="job-progress">
      {job.kind === "catalogue" && job.result.synthetic && (
        <p className="context-note">Synthetic fixture review</p>
      )}
      <div
        role={announce ? "status" : undefined}
        aria-label={
          announce ? `${progressNoun} progress for ${job.title}` : undefined
        }
      >
        <p className={`state state-${job.state}`}>
          <strong>
            {job.state === "running" && validation
              ? "Running EPUBCheck"
              : job.state === "running" && job.kind === "catalogue"
                ? "Reviewing"
                : job.state === "running" && epub
                  ? "Inspecting"
                  : job.state === "running" && libraryCheck
                    ? "Checking"
                    : (stateLabel[job.state] ?? job.state)}
          </strong>
          {!indeterminate && ["queued", "running"].includes(job.state) && (
            <span>{job.checkpoint} / 4 steps</span>
          )}
        </p>
        {job.state === "failed" && (
          <p className="error">
            {job.message.trim() || "This attempt could not finish."}
          </p>
        )}
      </div>
      {["queued", "running"].includes(job.state) && (
        <progress
          value={indeterminate ? undefined : job.checkpoint}
          max={indeterminate ? undefined : 4}
          aria-label={`${progressNoun} progress for ${job.title}`}
        />
      )}
      {!!job.result.findings?.length && (
        <>
          <ul className="findings">
            {job.result.findings.map((finding) => (
              <li key={finding.name}>
                <strong>
                  {finding.status
                    ? {
                        pass: "Passed",
                        attention: "Attention",
                        partial: "Partial",
                        not_checked: "Not checked",
                      }[finding.status]
                    : finding.ok
                      ? file
                        ? "Passed"
                        : "Agrees"
                      : file
                        ? "Attention"
                        : "Review"}{" "}
                  · {finding.name}
                </strong>
              </li>
            ))}
          </ul>
          <details className="finding-details">
            <summary>Finding details</summary>
            <ul className="finding-evidence">
              {job.result.findings.map((finding) => (
                <li key={finding.name}>
                  <FindingHeading>{finding.name}</FindingHeading>
                  <p>
                    {finding.detail.replace(
                      /\b1 recorded values are shown as excerpts\b/gu,
                      "1 recorded value is shown as an excerpt",
                    )}
                  </p>
                  {!!finding.missing?.length && (
                    <p>Not recorded: {finding.missing.join(", ")}</p>
                  )}
                  {!!finding.items?.length && (
                    <FindingEvidence
                      name={finding.name}
                      items={finding.items}
                    />
                  )}
                </li>
              ))}
            </ul>
          </details>
        </>
      )}
      <details data-job-record>
        <summary>
          {validation
            ? "EPUBCheck record"
            : libraryCheck
              ? "Library check record"
              : job.kind === "catalogue"
                ? "Review record"
                : "Inspection record"}
        </summary>
        {job.state !== "failed" && <p>{job.message}</p>}
        {job.result.scope && (
          <p className="context-note">
            {scopeInFindings
              ? "Scope appears in Finding details."
              : job.result.scope}
          </p>
        )}
        <dl className="provenance">
          <dt>Job</dt>
          <dd className="hash">{job.id}</dd>
          <dt>
            {validation
              ? "Validation policy"
              : epub
                ? "Inspection policy"
                : job.kind === "book_assessment"
                  ? "Catalogue version"
                  : "Source snapshot"}
          </dt>
          <dd>
            {libraryCheck
              ? catalogueVersion || HISTORICALLY_UNRECORDED
              : job.source_version}
          </dd>
          {(job.source_sha256 || libraryCheck) && (
            <>
              <dt>
                {job.kind === "book_assessment"
                  ? "EPUB source digest"
                  : file
                    ? "Source digest"
                    : "Snapshot digest"}
              </dt>
              <dd className="hash">
                {job.kind === "library_reconcile"
                  ? catalogueDigest || HISTORICALLY_UNRECORDED
                  : job.source_sha256 || HISTORICALLY_UNRECORDED}
              </dd>
            </>
          )}
          {assessment && (
            <>
              <dt>Catalogue digest</dt>
              <dd className="hash">
                {job.catalogue_sha256 || HISTORICALLY_UNRECORDED}
              </dd>
              <dt>Source inspection</dt>
              <dd className="hash">
                {job.source_job_id || HISTORICALLY_UNRECORDED}
              </dd>
              <dt>Source report digest</dt>
              <dd className="hash">
                {job.source_report_sha256 || HISTORICALLY_UNRECORDED}
              </dd>
              <dt>Catalogue work</dt>
              <dd>{job.catalogue_work_id || HISTORICALLY_UNRECORDED}</dd>
              <dt>Reconciliation</dt>
              <dd className="hash">
                {job.reconciliation_key || HISTORICALLY_UNRECORDED}
              </dd>
            </>
          )}
          <dt>Input fingerprint</dt>
          <dd className="hash">{job.input_fingerprint}</dd>
          <dt>Revision</dt>
          <dd>{job.revision}</dd>
          <dt>Attempt</dt>
          <dd>{job.attempts || "Waiting"}</dd>
          <dt>Checkpoint</dt>
          <dd>{job.checkpoint} / 4</dd>
          <dt>Updated</dt>
          <dd>{new Date(job.updated_at).toLocaleString()}</dd>
        </dl>
      </details>
    </div>
  );
}
