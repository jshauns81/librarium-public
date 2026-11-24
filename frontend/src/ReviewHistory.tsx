import React, { useEffect, useRef, useState } from "react";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { api, ApiError } from "./api";
import { EvidenceValue } from "./EvidenceValue";
import { JobProgress } from "./JobProgress";
import type { Job, JobHistory } from "./types";
import { isRetiredKind, retiredKindLabel } from "./retired-kinds";
import { trackReturnIntent } from "./return-intent";
import "./review-history.css";

export const reviewStates = [
  "active",
  "queued",
  "running",
  "succeeded",
  "failed",
  "cancelled",
];
export type ReviewRoute = { rq: string; rs: string; rp: number };
export const historyKinds = [
  "all",
  "synthetic",
  "catalogue",
  "epub",
  "epub_validation",
  "library_reconcile",
  "book_assessment",
  "retired",
];
export type HistoryKind =
  | ""
  | "synthetic"
  | "catalogue"
  | "epub"
  | "epub_validation"
  | "library_reconcile"
  | "book_assessment"
  | "retired";
export type ReviewReturn = {
  route: ReviewRoute;
  jobId: string;
  scroll: number;
};
// A retired job never progresses here, so it is not polled or cancellable.
const active = (job: Job) =>
  !isRetiredKind(job.kind) && ["queued", "running"].includes(job.state);
const emptyHistories: Record<HistoryKind, { heading: string; detail: string }> =
  {
    "": {
      heading: "No saved work yet",
      detail:
        "Book inspections, checks and reference reviews appear here after they run.",
    },
    catalogue: {
      heading: "No catalogue reviews yet",
      detail:
        "Catalogue metadata reviews are saved after reviewing a work and its source evidence.",
    },
    epub: {
      heading: "No file inspections yet",
      detail:
        "Preserved EPUB inspections and their structural findings appear here after an inspection.",
    },
    epub_validation: {
      heading: "No EPUBCheck validations yet",
      detail:
        "Source EPUBCheck attempts are saved after an explicit conformance check in a preserved book workspace.",
    },
    library_reconcile: {
      heading: "No library reconciliations yet",
      detail:
        "Saved reconciliations record the library evidence selected for a book assessment.",
    },
    book_assessment: {
      heading: "No candidate assessments yet",
      detail:
        "Assessments of book identity and possible duplicates are saved from a preserved book workspace.",
    },
    retired: {
      heading: "No retired records",
      detail:
        "Review copies and library deliveries are no longer made. Older records of them would appear here.",
    },
    synthetic: {
      heading: "No synthetic inspections yet",
      detail:
        "Demonstration metadata checks appear here if they were run in a demo collection.",
    },
  };

export function ReviewHistory({
  route,
  navigate,
  realLibrary,
  enabled,
  latestJobs,
  open,
  cancel,
  cancelling,
  restore,
  browse,
  chooseSource,
  announceTerminal,
  kind: kindProp,
  selectKind,
  selectedId,
  closeSelected,
}: {
  route: ReviewRoute;
  navigate: (route: Partial<ReviewRoute>, push?: boolean) => void;
  realLibrary: boolean;
  kind?: HistoryKind;
  selectKind?: (kind: HistoryKind) => void;
  selectedId?: string;
  closeSelected?: () => void;
  enabled: boolean;
  latestJobs: Job[];
  open: (job: Job) => void;
  cancel: (job: Job) => void;
  cancelling?: string;
  restore?: ReviewReturn;
  browse: () => void;
  chooseSource?: () => void;
  announceTerminal: (jobs: Job[]) => void;
}) {
  const [search, setSearch] = useState(route.rq);
  useEffect(() => setSearch(route.rq), [route.rq]);
  const client = useQueryClient();
  const kind: HistoryKind = kindProp ?? (realLibrary ? "catalogue" : "");
  const files = kind === "epub";
  const noun = files ? "inspection" : "review";
  const empty = emptyHistories[kind];
  const emptyAction =
    kind !== "catalogue" &&
    kind !== "synthetic" &&
    kind !== "retired" &&
    chooseSource
      ? {
          label: files ? "Choose an EPUB" : "Open book workspaces",
          run: chooseSource,
        }
      : !kind || kind === "catalogue" || (kind === "synthetic" && !realLibrary)
        ? {
            label: realLibrary ? "Browse catalogue" : "Browse collection",
            run: browse,
          }
        : null;
  const searchId = files ? "file-history-search" : "review-history-search";
  const key = JSON.stringify([kind, route.rq, route.rs, route.rp]);
  const summary = useRef<HTMLDivElement>(null);
  const focusAfterRequest = useRef<{
    key: string;
    intent: ReturnType<typeof trackReturnIntent>;
  } | null>(null);
  function requestSummaryFocus(nextKey: string) {
    focusAfterRequest.current?.intent.dispose();
    summary.current?.focus({ preventScroll: true });
    const intent = trackReturnIntent(
      () => {
        focusAfterRequest.current = null;
      },
      { includeCurrentFocus: true },
    );
    focusAfterRequest.current = { key: nextKey, intent };
  }
  useEffect(() => () => focusAfterRequest.current?.intent.dispose(), []);
  const history = useQuery({
    queryKey: ["review-history", kind, route.rq, route.rs, route.rp],
    enabled,
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({
        q: route.rq,
        state: route.rs,
        page: String(route.rp),
      });
      if (kind) params.set("kind", kind);
      return {
        ...(await api<JobHistory>(`jobs/history?${params}`, { signal })),
        key,
      };
    },
    retry: false,
    placeholderData: keepPreviousData,
    refetchInterval: (query) =>
      !query.state.error &&
      kind !== "retired" &&
      (query.state.data?.jobs.some(active) ||
        ["active", "queued", "running"].includes(route.rs))
        ? 1500
        : false,
  });
  const saved = useRef<(JobHistory & { key: string }) | undefined>(undefined);
  if (history.data && !history.isPlaceholderData) saved.current = history.data;
  const page = history.data ?? saved.current;
  const replacing = !!page && page.key !== key;
  const revisions = useRef(new Map<string, Job>());
  for (const job of [...(page?.jobs ?? []), ...latestJobs]) {
    const previous = revisions.current.get(job.id);
    if (!previous || job.revision > previous.revision)
      revisions.current.set(job.id, job);
  }
  const rows =
    page?.jobs.map((job) => revisions.current.get(job.id) ?? job) ?? [];
  const previousPoll = useRef<Job[] | undefined>(undefined);
  useEffect(() => {
    const previous = previousPoll.current;
    previousPoll.current = latestJobs;
    if (
      previous &&
      latestJobs.some((job) => {
        const old = previous.find((value) => value.id === job.id);
        return !old || old.state !== job.state;
      })
    )
      void client.invalidateQueries({ queryKey: ["review-history"] });
  }, [latestJobs, client]);
  useEffect(() => {
    announceTerminal(rows);
  }, [page, latestJobs, announceTerminal]);
  const pages = Math.max(
    1,
    Math.ceil((page?.total ?? 0) / (page?.page_size ?? 24)),
  );
  useEffect(() => {
    const pending = focusAfterRequest.current;
    if (!pending) return;
    if (pending.key !== key || !pending.intent.isCurrent()) {
      pending.intent.dispose();
      focusAfterRequest.current = null;
      return;
    }
    if (history.isFetching || replacing || history.isError || !page) return;
    pending.intent.dispose();
    focusAfterRequest.current = null;
    summary.current?.focus({ preventScroll: true });
    summary.current?.scrollIntoView({ block: "start" });
  }, [key, history.isFetching, history.isError, replacing, page]);
  useEffect(() => {
    if (
      history.data &&
      !history.isPlaceholderData &&
      !history.isError &&
      route.rp > pages
    )
      navigate({ rp: pages });
  }, [
    history.data,
    history.isPlaceholderData,
    history.isError,
    route.rp,
    pages,
  ]);
  const restored = useRef(false);
  useEffect(() => {
    if (!restore || restored.current || replacing || !page) return;
    const frame = requestAnimationFrame(() => {
      const target =
        document.getElementById(`review-open-${restore.jobId}`) ??
        document.getElementById(searchId);
      target?.focus({ preventScroll: true });
      window.scrollTo(0, restore.scroll);
      restored.current = true;
    });
    return () => cancelAnimationFrame(frame);
  }, [restore, replacing, page]);
  function clear() {
    setSearch("");
    navigate({ rq: "", rs: "", rp: 1 }, true);
  }
  function changePage(value: number) {
    if (history.isFetching || replacing) return;
    requestSummaryFocus(JSON.stringify([kind, route.rq, route.rs, value]));
    navigate({ rp: value }, true);
  }
  function retry() {
    if (history.isFetching) return;
    requestSummaryFocus(key);
    void history.refetch();
  }
  // Closing a selected record (button or browser Back) returns focus to its row.
  const previousSelection = useRef(selectedId ?? "");
  const openedScroll = useRef(0);
  useEffect(() => {
    const previous = previousSelection.current;
    previousSelection.current = selectedId ?? "";
    if (!previous || selectedId) return;
    const row = document.getElementById(`review-open-${previous}`);
    if (!row) return;
    row.focus({ preventScroll: true });
    window.scrollTo(0, openedScroll.current);
  }, [selectedId]);
  const filtered = !!route.rq || !!route.rs;
  return (
    <section
      className="history review-history"
      aria-label={files ? "File inspection history" : "Review history"}
    >
      <p className="review-history-intro">
        {files
          ? "Preserved EPUB files with their recorded source digests and recorded structural findings. File inspections do not run EPUBCheck, identify a work or establish library ownership."
          : "Saved book work and reference reviews. Open a record for its original scope and evidence; stored history does not establish current library ownership."}
        {kind === "" &&
          " Synthetic metadata inspections and EPUB file inspections are labelled separately."}
      </p>
      {selectedId && (
        <SelectedLibraryCheck
          key={selectedId}
          id={selectedId}
          enabled={enabled}
          latestJobs={latestJobs}
          cancel={cancel}
          cancelling={cancelling}
          close={() => closeSelected?.()}
          announceTerminal={announceTerminal}
        />
      )}
      <form
        className="review-history-filters"
        role="search"
        aria-label={files ? "File inspection history" : "Review history"}
        onSubmit={(event) => {
          event.preventDefault();
          navigate({ rq: search, rp: 1 }, true);
        }}
      >
        {selectKind && (
          <label>
            Record kind
            <select
              value={kind || "all"}
              onChange={(event) =>
                selectKind(
                  event.target.value === "all"
                    ? ""
                    : (event.target.value as HistoryKind),
                )
              }
            >
              <option value="all">All records</option>
              <option value="catalogue">Catalogue metadata reviews</option>
              <option value="epub">EPUB file inspections</option>
              <option value="epub_validation">EPUBCheck validations</option>
              <option value="library_reconcile">Library reconciliations</option>
              <option value="book_assessment">Candidate assessments</option>
              <option value="synthetic">Synthetic metadata inspections</option>
              <option value="retired">
                Retired: review copies and delivery
              </option>
            </select>
          </label>
        )}
        <label className="search" htmlFor={searchId}>
          {files ? "Search file inspections" : "Search reviews"}
          <input
            id={searchId}
            type="search"
            maxLength={200}
            placeholder={
              files ? "Part of a file name" : "Part of a captured title"
            }
            value={search}
            onChange={(event) => setSearch(event.target.value)}
          />
        </label>
        <button type="submit">
          {files ? "Search file inspections" : "Search reviews"}
        </button>
        <label>
          {files ? "Inspection state" : "Review state"}
          <select
            value={route.rs}
            onChange={(event) =>
              navigate({ rs: event.target.value, rq: search, rp: 1 }, true)
            }
          >
            <option value="">All states</option>
            <option value="active">Active</option>
            <option value="queued">Queued</option>
            <option value="running">Running</option>
            <option value="succeeded">Complete</option>
            <option value="failed">Failed</option>
            <option value="cancelled">Cancelled</option>
          </select>
        </label>
        {filtered && (
          <button type="button" onClick={clear}>
            {files ? "Clear inspection filters" : "Clear review filters"}
          </button>
        )}
      </form>
      <div
        ref={summary}
        tabIndex={-1}
        className="review-history-summary"
        role="status"
        aria-live="polite"
      >
        {history.isFetching && (!page || replacing)
          ? `Loading page ${route.rp}…${page ? " Previous results remain visible." : ""}`
          : history.isError
            ? page
              ? "Previous results are out of date. Retry to check the requested history."
              : `${files ? "File inspection" : "Review"} history is unavailable.`
            : page
              ? page.total
                ? `${((page.page - 1) * page.page_size + 1).toLocaleString()}–${Math.min(page.page * page.page_size, page.total).toLocaleString()} of ${page.total.toLocaleString()} ${page.total === 1 ? noun : `${noun}s`}`
                : `0 ${noun}s`
              : `Loading ${noun} history…`}
      </div>
      {history.isError && (
        <div className="error" role="alert">
          <p>
            {files ? "File inspection" : "Review"} history could not load:{" "}
            {history.error.message}
          </p>
          <button onClick={retry} aria-disabled={history.isFetching}>
            {files ? "Retry inspection history" : "Retry review history"}
          </button>
        </div>
      )}
      <div
        className="review-history-results"
        aria-busy={replacing && history.isFetching}
        inert={replacing}
      >
        {page?.total === 0 && !history.isError && !replacing && (
          <div className="empty">
            <h2>
              {filtered ? `No ${noun}s match these filters` : empty.heading}
            </h2>
            <p>
              {filtered
                ? files
                  ? "Try another part of a file name or a different state."
                  : "Try another part of a captured title or a different state."
                : empty.detail}
            </p>
            {!filtered && emptyAction && (
              <button onClick={emptyAction.run}>{emptyAction.label}</button>
            )}
          </div>
        )}
        {rows.map((job) => (
          <article
            className="history-row"
            id={`inspection-${job.id}`}
            key={job.id}
          >
            <div className="review-history-work">
              <h2>
                {isRetiredKind(job.kind) ? (
                  job.title
                ) : (
                  <button
                    id={`review-open-${job.id}`}
                    className="text-button"
                    onClick={() => {
                      openedScroll.current = window.scrollY;
                      open(job);
                    }}
                  >
                    {job.title}
                  </button>
                )}
              </h2>
              <p className="review-history-kind">
                {job.kind === "epub"
                  ? "EPUB file inspection"
                  : job.kind === "epub_validation"
                    ? "EPUBCheck validation"
                    : job.kind === "catalogue"
                      ? "Catalogue metadata review"
                      : job.kind === "library_reconcile"
                        ? "Library reconciliation"
                        : job.kind === "book_assessment"
                          ? "Book identity and duplicate assessment"
                          : isRetiredKind(job.kind)
                            ? `${retiredKindLabel(job.kind)} (retired feature)`
                            : "Synthetic metadata inspection"}
              </p>
              <p>
                Updated{" "}
                <time dateTime={job.updated_at}>
                  {new Date(job.updated_at).toLocaleString(undefined, {
                    dateStyle: "medium",
                    timeStyle: "short",
                  })}
                </time>
              </p>
            </div>
            <div className="review-history-progress">
              <JobProgress job={job} findingsLevel={3} />
              {active(job) && (
                <button
                  className="cancel"
                  disabled={cancelling === job.id}
                  onClick={() => cancel(job)}
                >
                  {cancelling === job.id
                    ? "Cancelling…"
                    : job.kind === "epub_validation"
                      ? "Cancel EPUBCheck"
                      : job.kind === "catalogue"
                        ? "Cancel review"
                        : ["library_reconcile", "book_assessment"].includes(
                              job.kind ?? "",
                            )
                          ? "Cancel check"
                          : "Cancel inspection"}
                </button>
              )}
            </div>
          </article>
        ))}
      </div>
      {!!page?.total && (
        <nav
          className="pagination"
          aria-label={
            files ? "File inspection history pages" : "Review history pages"
          }
        >
          <button
            aria-label="Previous page"
            onClick={() => changePage(Math.max(1, route.rp - 1))}
            disabled={route.rp === 1}
            aria-disabled={history.isFetching || replacing}
          >
            Previous
          </button>
          <span>
            Page {page.page} of {pages}
          </span>
          <button
            aria-label="Next page"
            onClick={() => changePage(route.rp + 1)}
            aria-disabled={history.isFetching || replacing}
            disabled={route.rp >= pages || route.rp >= 10000}
          >
            Next
          </button>
        </nav>
      )}
    </section>
  );
}

function SelectedLibraryCheck({
  id,
  enabled,
  latestJobs,
  cancel,
  cancelling,
  close,
  announceTerminal,
}: {
  id: string;
  enabled: boolean;
  latestJobs: Job[];
  cancel: (job: Job) => void;
  cancelling?: string;
  close: () => void;
  announceTerminal: (jobs: Job[]) => void;
}) {
  const container = useRef<HTMLElement>(null);
  const query = useQuery<Job>({
    queryKey: ["review-check", id],
    enabled,
    queryFn: async ({ signal }) => {
      const job = await api<Job>(`jobs/${encodeURIComponent(id)}`, { signal });
      if (
        job.id !== id ||
        !(
          ["book_assessment", "library_reconcile"].includes(job.kind ?? "") ||
          isRetiredKind(job.kind)
        )
      )
        throw new ApiError(
          "This record is not a saved library check. Close this selection and open its original history record.",
          409,
          "record_kind_mismatch",
        );
      return job;
    },
    retry: false,
    refetchInterval: (value) =>
      value.state.data && active(value.state.data) ? 1500 : false,
    structuralSharing: (previous, incoming) => {
      const old = previous as Job | undefined;
      const next = incoming as Job;
      return old && old.revision > next.revision ? old : next;
    },
  });
  const polled = latestJobs.find((job) => job.id === id);
  const fetched = query.data?.id === id ? query.data : undefined;
  const job =
    fetched && polled && polled.revision > fetched.revision ? polled : fetched;
  const focused = useRef(false);
  useEffect(() => {
    if (!job || focused.current) return;
    const details =
      container.current?.querySelector<HTMLDetailsElement>("[data-job-record]");
    if (details) details.open = true;
    container.current
      ?.querySelector<HTMLHeadingElement>("h2")
      ?.focus({ preventScroll: true });
    focused.current = true;
  }, [job]);
  useEffect(() => {
    if (job) announceTerminal([job]);
  }, [job, announceTerminal]);
  if (!job)
    return query.isError ? (
      <div className="error" role="alert">
        <p>The selected check could not load: {query.error.message}</p>
        {!(
          query.error instanceof ApiError &&
          query.error.code === "record_kind_mismatch"
        ) && (
          <button onClick={() => void query.refetch()}>
            Retry selected check
          </button>
        )}
        <button onClick={close}>Close check record</button>
      </div>
    ) : (
      <p role="status">Loading selected check record…</p>
    );
  return (
    <section
      ref={container}
      className="selected-library-check"
      aria-label="Selected library check record"
    >
      <h2 tabIndex={-1}>{job.title}</h2>
      <p className="context-note">
        {isRetiredKind(job.kind)
          ? "A record from a retired feature. Librarium no longer makes or delivers review copies, so nothing further is kept here."
          : `Recorded ${
              job.kind === "library_reconcile"
                ? "library reconciliation"
                : "candidate assessment"
            }. Inputs and findings belong to this specific check.`}
      </p>
      {query.isError && (
        <div className="error" role="alert">
          <p>Progress could not refresh. The saved record remains visible.</p>
          <button onClick={() => void query.refetch()}>
            Retry selected check
          </button>
        </div>
      )}
      <JobProgress job={job} announce />
      {active(job) && (
        <button
          className="cancel"
          disabled={cancelling === job.id}
          onClick={() => cancel(job)}
        >
          {cancelling === job.id ? "Cancelling…" : "Cancel check"}
        </button>
      )}
      {!isRetiredKind(job.kind) && (
        <details>
          <summary>Saved check result</summary>
          <EvidenceValue value={job.result} />
        </details>
      )}
      <button onClick={close}>Close check record</button>
    </section>
  );
}
