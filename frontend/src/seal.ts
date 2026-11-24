import type { Job } from "./types";

/**
 * A wax seal means one thing: the structure check finished, passed, flagged
 * nothing and proposed no contents change. Warnings or a proposed fix mean
 * there is something to look at, so no seal.
 */
export function checkedSound(job: Job | undefined) {
  if (!job || job.kind !== "epub" || job.state !== "succeeded") return false;
  const result = job.result;
  if (!result || typeof result !== "object") return false;
  return (
    result.structural_check === "passed" &&
    result.inspection_complete === true &&
    (Array.isArray(result.findings) ? result.findings : []).every(
      (finding) =>
        finding.ok === true &&
        (finding.status === undefined || finding.status === "pass"),
    ) &&
    (!result.contents_plan || result.contents_plan.decision === "keep")
  );
}

/** The checked copy must still be the file on the shelf: same size as recorded now. */
export function sameFile(job: Job, currentSize: number | null | undefined) {
  const checked = job.source_size ?? job.result?.source_size;
  return (
    typeof checked === "number" &&
    typeof currentSize === "number" &&
    checked === currentSize
  );
}
