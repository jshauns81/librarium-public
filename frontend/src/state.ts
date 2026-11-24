import { isRetiredKind } from "./retired-kinds";
import type { Job } from "./types";

export function mergeJobs(current: Job[], incoming: Job[]): Job[] {
  const values = new Map(current.map((job) => [job.id, job]));
  for (const job of incoming) {
    const previous = values.get(job.id);
    if (!previous || job.revision > previous.revision) values.set(job.id, job);
  }
  return Array.from(values.values());
}

export function intentKey(
  storage: Pick<Storage, "getItem" | "setItem">,
  work: string,
): string {
  const name = `librarium-intent:${work}`;
  let key = storage.getItem(name);
  if (!key) {
    key = crypto.randomUUID();
    storage.setItem(name, key);
  }
  return key;
}

export function createTerminalAnnouncer(announce: (message: string) => void) {
  const known = new Set<string>();
  const announced = new Set<string>();
  const labels: Record<string, string> = {
    succeeded: "completed",
    failed: "failed",
    cancelled: "cancelled",
  };
  return (jobs: Job[]) => {
    const messages: string[] = [];
    for (const job of jobs) {
      if (labels[job.state]) {
        if (
          known.has(job.id) &&
          !announced.has(job.id) &&
          !isRetiredKind(job.kind)
        ) {
          const noun =
            job.kind === "epub_validation"
              ? "EPUBCheck"
              : job.kind === "catalogue"
                ? "review"
                : job.kind === "library_reconcile"
                  ? "library reconciliation"
                  : job.kind === "book_assessment"
                    ? "candidate assessment"
                    : "inspection";
          messages.push(
            `${job.title}: ${noun} ${labels[job.state]}. ${job.message}`,
          );
        }
        announced.add(job.id);
      }
      known.add(job.id);
    }
    if (messages.length) announce(messages.join(" "));
  };
}

export function commandNotice(action: "inspect" | "cancel", job: Job): string {
  const noun =
    job.kind === "epub_validation"
      ? "EPUBCheck"
      : job.kind === "catalogue"
        ? "Review"
        : job.kind === "library_reconcile"
          ? "Library reconciliation"
          : job.kind === "book_assessment"
            ? "Candidate assessment"
            : "Inspection";
  if (job.state === "succeeded")
    return `${noun} already completed. Its saved result is available.`;
  if (job.state === "failed")
    return `${noun} already failed. Review its error before retrying.`;
  if (job.state === "cancelled") return `${noun} cancelled.`;
  if (action === "cancel")
    return "Cancellation is not confirmed. Refresh progress.";
  if (job.state === "running")
    return `${noun} is already running. Follow its progress.`;
  return `${noun} queued. You can keep browsing.`;
}
