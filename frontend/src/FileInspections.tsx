import React, { useEffect, useId, useRef, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import type { DirectLibraryBook } from "./DirectLibrary";
import { trackReturnIntent } from "./return-intent";
import { api, ApiError } from "./api";
import { commandNotice } from "./state";
import { JobProgress } from "./JobProgress";
import {
  BookWorkspaceContext,
  clearWorkspace,
  fetchWorkspace,
  workspaceKeys,
  WorkspaceRefusal,
  useBookWorkspace,
  type WorkspaceRoute,
} from "./book-workspace";
import { ResumedAssessment } from "./CandidateAssessment";
import { PackageComparison } from "./PackageComparison";
import { catalogueComparisonTarget } from "./author-groups-api";
import { SourceAttribution } from "./SourceAttribution";
import { IdentifierDeclarations } from "./IdentifierDeclarations";
import { EpubValidation } from "./EpubValidation";
import { ReviewHistory, type ReviewReturn } from "./ReviewHistory";
import type { EpubReport, EpubReportEnvelope, Job, Session } from "./types";
import {
  clearIntent,
  DEFAULT_MAX_BYTES,
  describeFinding,
  digestBytes,
  fetchReport,
  formatBytes,
  lookupInspection,
  readIntent,
  reportBinds,
  sourceName,
  UPLOAD_DEADLINE_MS,
  uploadEpub,
  writeIntent,
  type FileIntent,
} from "./file-inspection-api";
import "./file-inspections.css";

export type FileRoute = WorkspaceRoute & {
  fj: string;
  fv?: string;
  fa?: string;
  fq: string;
  fs: string;
  fp: number;
  fcw?: string;
  fcv?: string;
  fch?: string;
};
export type FileReturn = ReviewReturn;
const live = (job: Job) => ["queued", "running"].includes(job.state);

function BookSectionLink({
  target,
  children,
}: {
  target: string;
  children: React.ReactNode;
}) {
  return (
    <a
      href={`#${target}`}
      onClick={() =>
        document.getElementById(target)?.focus({ preventScroll: true })
      }
    >
      {children}
    </a>
  );
}

function sourceCondition(job: Job) {
  if (job.state === "succeeded")
    return job.result.structural_check === "passed"
      ? "Source structural checks passed"
      : job.result.structural_check === "failed"
        ? "Source structural findings need attention"
        : "Source structural result unavailable";
  return {
    queued: "Source inspection queued",
    running: "Inspecting the preserved source",
    failed: "Source inspection failed",
    cancelled: "Source inspection cancelled",
  }[job.state];
}

function structuralWarnings(report: EpubReport | undefined) {
  const findings: unknown = report?.findings;
  const finding = (
    value: unknown,
  ): value is NonNullable<EpubReport["findings"]>[number] =>
    !!value &&
    typeof value === "object" &&
    "code" in value &&
    typeof value.code === "string" &&
    "severity" in value &&
    typeof value.severity === "string" &&
    (!("path" in value) ||
      value.path == null ||
      typeof value.path === "string");
  return Array.isArray(findings) && findings.every(finding)
    ? findings.filter((value) => value.severity === "warning")
    : undefined;
}

type Attempt = {
  intent: FileIntent;
  outcome: "unconfirmed" | "refused";
  recorded: "checking" | "missing" | "unknown";
  reason: string;
  status?: number;
};

export function FileInspections({
  route,
  navigate,
  session,
  sessionPending,
  sessionError,
  retrySession,
  jobs,
  merge,
  cancel,
  cancelling,
  announceTerminal,
  restore,
  back,
  returnToReviews,
  notify,
  returnToCatalogue,
  returnToLibrary,
  browseReferences,
  restoreWorkspace,
  libraryContext,
}: {
  route: FileRoute;
  navigate: (next: Partial<FileRoute>, push?: boolean, state?: unknown) => void;
  session: Session | undefined;
  sessionPending: boolean;
  sessionError: Error | null;
  retrySession: () => void;
  jobs: Job[];
  merge: (job: Job) => void;
  cancel: (job: Job) => void;
  cancelling?: string;
  announceTerminal: (jobs: Job[]) => void;
  restore?: FileReturn;
  back?: () => void;
  returnToReviews: () => void;
  notify: (message: string) => void;
  returnToCatalogue?: () => void;
  returnToLibrary?: () => void;
  browseReferences?: () => void;
  restoreWorkspace?: { scroll: number; focusId?: string };
  libraryContext?: {
    route: { lw: string; lt: string };
    book?: DirectLibraryBook;
  };
}) {
  const configured = !!session?.file_inspections;
  const comparisonTarget = catalogueComparisonTarget(
    route.fcw,
    route.fcv,
    route.fch,
  );
  const clearComparisonTarget = () => {
    currentSelection.current = {
      ...currentSelection.current,
      fcw: "",
      fcv: "",
      fch: "",
    };
    navigate({ fcw: "", fcv: "", fch: "" });
  };
  function currentComparison() {
    const latest = currentSelection.current;
    return !latest.fj
      ? catalogueComparisonTarget(latest.fcw, latest.fcv, latest.fch)
      : undefined;
  }
  function prospectiveComparison() {
    const target = currentComparison();
    return target
      ? {
          fcw: target.work,
          fcv: target.version,
          fch: target.sha256,
        }
      : {};
  }
  function comparisonOrigin() {
    return currentComparison() && history.state?.catalogueComparisonOrigin
      ? { catalogueComparisonOrigin: history.state.catalogueComparisonOrigin }
      : {};
  }
  const maxBytes = session?.file_inspection_max_bytes ?? DEFAULT_MAX_BYTES;
  const limitLabel = `${Math.round(maxBytes / (1024 * 1024))} MiB`;
  const input = useRef<HTMLInputElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const [coverFailed, setCoverFailed] = useState("");
  const busy = useRef(false);
  const attemptFile = useRef<File | null>(null);
  const activeAttempt = useRef<AbortController | null>(null);
  const focusSelected = useRef(false);
  const [file, setFile] = useState<File | null>(null);
  const [rejection, setRejection] = useState("");
  const [stage, setStage] = useState<"idle" | "hashing" | "uploading">("idle");
  const [attempt, setAttempt] = useState<Attempt | null>(null);

  const cached = jobs.find((job) => job.kind === "epub" && job.id === route.fj);
  const detail = useQuery<Job>({
    queryKey: ["file-job", route.fj],
    enabled: !!route.fj && !cached && !!session,
    queryFn: async ({ signal }) => {
      const job = await api<Job>(`jobs/${encodeURIComponent(route.fj)}`, {
        signal,
      });
      if (job.kind !== "epub" || job.id !== route.fj)
        throw new ApiError("File inspection not found", 404);
      return job;
    },
    retry: false,
    refetchInterval: (query) =>
      query.state.data && live(query.state.data) ? 1500 : false,
  });
  const fetched = detail.data?.id === route.fj ? detail.data : undefined;
  const preliminarySelected =
    cached && fetched
      ? fetched.revision > cached.revision
        ? fetched
        : cached
      : (cached ?? fetched);

  const workspace = useQuery({
    queryKey: [
      "book-workspace",
      route.fj,
      preliminarySelected?.revision,
      ...workspaceKeys.map((key) => route[key] ?? ""),
    ],
    enabled: !!route.fj && !!session,
    queryFn: ({ signal }) => fetchWorkspace(route.fj, route, signal),
    retry: false,
    refetchInterval: (query) =>
      query.state.data &&
      [query.state.data.source, ...query.state.data.jobs].some(live)
        ? 1500
        : false,
  });
  const fresh =
    workspace.data?.source.id === route.fj ? workspace.data : undefined;
  const retained = useRef<typeof fresh>(undefined);
  if (retained.current?.source.id !== route.fj) retained.current = undefined;
  if (fresh) retained.current = fresh;
  const recorded = fresh ?? retained.current;
  const refused =
    workspace.isError &&
    (workspace.error instanceof WorkspaceRefusal ||
      (workspace.error instanceof ApiError &&
        workspace.error.status < 500 &&
        ![408, 429].includes(workspace.error.status)));
  const verified = !!fresh && !refused;
  const selected = recorded?.source ?? preliminarySelected;
  const structuralReport = useStructuralReport(selected, verified);
  const structuralWarningCount = structuralWarnings(
    structuralReport.data?.report,
  )?.length;
  const [findingsRequest, setFindingsRequest] = useState<{
    job: string;
    digest: string | undefined;
    sequence: number;
  } | null>(null);
  const libraryBook =
    recorded?.origin &&
    libraryContext &&
    recorded.origin.book_id === libraryContext.route.lw &&
    recorded.origin.inventory === libraryContext.route.lt
      ? libraryContext.book
      : undefined;
  const currentSelection = useRef(route);
  currentSelection.current = route;
  const pendingSelection = useRef<{
    source: string;
    element: HTMLElement | null;
    scroll: number;
    intent: ReturnType<typeof trackReturnIntent>;
  } | null>(null);
  const selectWorkspace = (
    pins: WorkspaceRoute & { fcw?: string; fcv?: string; fch?: string },
  ) => {
    if (verified && currentSelection.current === route) {
      pendingSelection.current?.intent.dispose();
      const target = {
        source: route.fj,
        element: document.activeElement as HTMLElement | null,
        scroll: window.scrollY,
        intent: trackReturnIntent(
          () => {
            pendingSelection.current = null;
          },
          { includeCurrentFocus: true },
        ),
      };
      pendingSelection.current = target;
      navigate(pins, true);
    }
  };
  useEffect(() => {
    const target = pendingSelection.current;
    if (!target) return;
    if (target.source !== route.fj) {
      target.intent.dispose();
      pendingSelection.current = null;
      return;
    }
    if (!verified || !target.intent.isCurrent()) return;
    target.intent.dispose();
    pendingSelection.current = null;
    const element = target.element?.isConnected
      ? target.element
      : (document.querySelector<HTMLElement>(
          '[aria-label="Selected book assessment"] h3',
        ) ?? heading.current);
    if (element) {
      if (!element.matches("button,input,select,textarea,a[href],[tabindex]"))
        element.tabIndex = -1;
      element.focus({ preventScroll: true });
    }
    window.scrollTo(0, target.scroll);
  }, [fresh, verified, route.fj]);
  useEffect(() => () => pendingSelection.current?.intent.dispose(), []);
  const workspaceReturn = useRef<{
    saved: typeof restoreWorkspace;
    intent: ReturnType<typeof trackReturnIntent>;
  } | null>(null);
  useEffect(() => {
    if (!restoreWorkspace) return;
    const intent = trackReturnIntent(() => {
      workspaceReturn.current = null;
    });
    workspaceReturn.current = { saved: restoreWorkspace, intent };
    return () => intent.dispose();
  }, [restoreWorkspace]);
  useEffect(() => {
    const target = workspaceReturn.current;
    if (!verified || !recorded || !target?.intent.isCurrent()) return;
    target.intent.dispose();
    workspaceReturn.current = null;
    focusSelected.current = false;
    (
      document.getElementById(target.saved?.focusId ?? "") ?? heading.current
    )?.focus({ preventScroll: true });
    window.scrollTo(0, target.saved?.scroll ?? 0);
  }, [recorded, verified]);

  function beginAttempt() {
    activeAttempt.current?.abort();
    const controller = new AbortController();
    activeAttempt.current = controller;
    return controller;
  }
  function abandonAttempt() {
    activeAttempt.current?.abort();
    activeAttempt.current = null;
    busy.current = false;
    setStage("idle");
    setAttempt((current) =>
      current?.recorded === "checking"
        ? { ...current, recorded: "unknown" }
        : current,
    );
  }
  function reset() {
    activeAttempt.current?.abort();
    activeAttempt.current = null;
    busy.current = false;
    setStage("idle");
    setFile(null);
    setRejection("");
    setAttempt(null);
    attemptFile.current = null;
    clearIntent(localStorage);
    if (input.current) input.current.value = "";
  }
  function confirm(job: Job, signal: AbortSignal) {
    if (signal.aborted) return;
    activeAttempt.current?.abort();
    clearIntent(localStorage, job.request_key);
    merge(job);
    setAttempt(null);
    setFile(null);
    attemptFile.current = null;
    if (input.current) input.current.value = "";
    focusSelected.current = true;
    navigate(
      { fj: job.id, ...clearWorkspace, ...prospectiveComparison() },
      true,
      comparisonOrigin(),
    );
    notify(commandNotice("inspect", job));
  }
  async function check(intent: FileIntent, signal: AbortSignal) {
    try {
      const job = await lookupInspection(intent.key, signal);
      if (signal.aborted) return;
      if (job.request_key === intent.key) {
        confirm(job, signal);
        return;
      }
      throw new Error("Lookup returned another request");
    } catch (error) {
      if (signal.aborted) return;
      const missing = error instanceof ApiError && error.status === 404;
      setAttempt((current) =>
        current && current.intent.key === intent.key
          ? { ...current, recorded: missing ? "missing" : "unknown" }
          : current,
      );
    }
  }
  async function inspect(freshKey: boolean) {
    if (busy.current || !file || !session || stage !== "idle") return;
    const controller = beginAttempt();
    busy.current = true;
    setRejection("");
    setStage("hashing");
    const previous = freshKey ? null : (attempt?.intent ?? null);
    setAttempt(null);
    let intent: FileIntent | null = null;
    try {
      const buffer = await file.arrayBuffer();
      if (controller.signal.aborted) return;
      const digest = await digestBytes(buffer);
      if (controller.signal.aborted) return;
      const name = sourceName(file.name);
      intent =
        previous && previous.digest === digest && previous.name === name
          ? previous
          : { key: crypto.randomUUID(), digest, name, size: file.size };
      writeIntent(localStorage, intent);
      attemptFile.current = file;
      setStage("uploading");
      const job = await uploadEpub({
        csrf: session.csrf,
        intent,
        body: buffer,
        signal: controller.signal,
      });
      confirm(job, controller.signal);
    } catch (error) {
      if (controller.signal.aborted) return;
      if (!intent) {
        setRejection(
          "The file could not be read in this browser. Choose it again.",
        );
      } else if (error instanceof ApiError) {
        setAttempt({
          intent,
          outcome: "refused",
          recorded: "unknown",
          reason: error.message,
          status: error.status,
        });
      } else {
        const timedOut =
          error instanceof DOMException && error.name === "TimeoutError";
        setAttempt({
          intent,
          outcome: "unconfirmed",
          recorded: "checking",
          reason: timedOut
            ? `the service did not answer within ${UPLOAD_DEADLINE_MS / 1000} seconds.`
            : "the connection dropped before the service answered.",
        });
        setStage("idle");
        busy.current = false;
        await check(intent, controller.signal);
      }
    } finally {
      if (activeAttempt.current === controller) {
        setStage("idle");
        busy.current = false;
      }
    }
  }
  function choose(event: React.ChangeEvent<HTMLInputElement>) {
    activeAttempt.current?.abort();
    activeAttempt.current = null;
    busy.current = false;
    setStage("idle");
    const chosen = event.target.files?.[0] ?? null;
    setRejection("");
    if (!chosen) {
      setFile(null);
      return;
    }
    if (chosen.size > maxBytes) {
      setFile(chosen);
      setRejection(
        `${chosen.name} is ${formatBytes(chosen.size)}, larger than the ${limitLabel} limit. It was not read or uploaded.`,
      );
      return;
    }
    setFile(chosen);
  }

  useEffect(
    () => () => {
      activeAttempt.current?.abort();
      activeAttempt.current = null;
    },
    [],
  );
  useEffect(() => {
    abandonAttempt();
  }, [route.fj]);
  useEffect(() => {
    if (!configured) return;
    const stored = readIntent(localStorage);
    if (!stored) return;
    const controller = route.fj ? null : beginAttempt();
    setAttempt({
      intent: stored,
      outcome: "unconfirmed",
      recorded: controller ? "checking" : "unknown",
      reason: "this page was closed or reloaded before the service answered.",
    });
    if (controller) void check(stored, controller.signal);
  }, [configured]);
  useEffect(() => {
    if (!attempt) return;
    const job = jobs.find((item) => item.request_key === attempt.intent.key);
    if (job && activeAttempt.current)
      confirm(job, activeAttempt.current.signal);
  }, [jobs, attempt]);
  useEffect(() => {
    announceTerminal(jobs);
  }, [jobs, announceTerminal]);
  useEffect(() => {
    if (!verified || !selected || !focusSelected.current || !heading.current)
      return;
    focusSelected.current = false;
    heading.current?.focus({ preventScroll: true });
    window.scrollTo(0, 0);
  }, [selected?.id, recorded?.source.id, verified]);
  useEffect(() => {
    if (route.fj && history.state?.reviewOrigin && !restoreWorkspace)
      focusSelected.current = true;
  }, [route.fj]);

  function openJob(job: Job) {
    abandonAttempt();
    const origin: FileReturn = {
      route: { rq: route.fq, rs: route.fs, rp: route.fp },
      jobId: job.id,
      scroll: window.scrollY,
    };
    history.replaceState({ ...history.state, fileReturn: origin }, "");
    focusSelected.current = true;
    navigate(
      { fj: job.id, ...clearWorkspace, ...prospectiveComparison() },
      true,
      { fileOrigin: origin, ...comparisonOrigin() },
    );
  }
  const heldFile = !!file && attemptFile.current === file;
  const shownName = file?.name ?? attempt?.intent.name;
  const shownSize = file?.size ?? attempt?.intent.size;
  const canInspect =
    !!file && !rejection && stage === "idle" && !(heldFile && attempt);

  const historyView = (
    <ReviewHistory
      kind="epub"
      route={{ rq: route.fq, rs: route.fs, rp: route.fp }}
      navigate={(next, push) =>
        navigate(
          {
            ...(next.rq !== undefined ? { fq: next.rq } : {}),
            ...(next.rs !== undefined ? { fs: next.rs } : {}),
            ...(next.rp !== undefined ? { fp: next.rp } : {}),
          },
          push,
        )
      }
      realLibrary={!!session?.library}
      enabled={!!session}
      latestJobs={jobs}
      open={openJob}
      cancel={cancel}
      cancelling={cancelling}
      restore={restore}
      browse={() => input.current?.focus()}
      chooseSource={
        configured && stage === "idle"
          ? () => input.current?.focus()
          : undefined
      }
      announceTerminal={announceTerminal}
    />
  );

  const selectedSection = route.fj && (
    <section
      className="file-section file-selected"
      aria-label="Selected inspection"
    >
      {refused && (
        <div className="error" role="alert">
          <h2>Saved workspace could not open</h2>
          <p>{workspace.error?.message}</p>
          <button onClick={() => void workspace.refetch()}>
            Retry saved workspace
          </button>
          <button onClick={() => navigate(clearWorkspace, true)}>
            Clear related selections
          </button>
          <p>
            The preserved source remains unchanged. Reopen an exact record from
            its history.
          </p>
        </div>
      )}
      {workspace.isError && !refused && (
        <div role="status">
          Saved workspace could not refresh.{" "}
          {recorded
            ? "The last confirmed book and results remain available."
            : "No workspace has been confirmed. Retry to check this preserved source."}
          <button onClick={() => void workspace.refetch()}>
            Retry saved workspace
          </button>
        </div>
      )}
      {!verified && !workspace.isError && (
        <p role="status">
          Checking this book's saved selections…{" "}
          {recorded &&
            "Showing the previous confirmed selection. New work waits for verification; cancellation and request recovery remain available."}
        </p>
      )}
      {selected && recorded && (
        <div key={selected.id} aria-busy={!verified}>
          <BookWorkspaceContext.Provider
            value={{
              value: recorded,
              select: selectWorkspace,
              ready: verified,
            }}
          >
            <>
              <div className="book-workspace-heading">
                {libraryBook?.cover &&
                  coverFailed !== libraryBook.cover.url && (
                    <img
                      className="book-workspace-cover"
                      src={libraryBook.cover.url}
                      alt=""
                      onError={() => setCoverFailed(libraryBook.cover!.url)}
                    />
                  )}
                <div>
                  <h1
                    ref={heading}
                    tabIndex={-1}
                    className="work-title file-title"
                  >
                    {libraryBook?.title || selected.title}
                  </h1>
                  {libraryBook && (
                    <>
                      <p className="author">
                        {libraryBook.authors.join(", ") ||
                          "Author not recorded"}
                      </p>
                      {libraryBook.series && (
                        <p className="series-detail">{libraryBook.series}</p>
                      )}
                    </>
                  )}
                </div>
              </div>
              <p
                className="book-condition-summary"
                role="status"
                aria-label="Source condition"
              >
                <strong>{sourceCondition(selected)}.</strong>{" "}
                {!!structuralWarningCount &&
                  `${structuralWarningCount.toLocaleString()} recorded structural ${structuralWarningCount === 1 ? "warning" : "warnings"}. `}
                This inspection reads the file and leaves library files
                unchanged.
              </p>
              <nav
                className="actions book-sections"
                aria-label="Book workspace sections"
              >
                <BookSectionLink target="book-condition">
                  Condition
                </BookSectionLink>
                {selected.state === "succeeded" &&
                  selected.result.report_url && (
                    <BookSectionLink target="book-reference">
                      Reference
                    </BookSectionLink>
                  )}
              </nav>
              <p className="file-kind">
                {recorded.origin ? "Preserved library EPUB" : "Incoming EPUB"} ·
                recorded {new Date(selected.updated_at).toLocaleString()}
              </p>
              <p className="context-note">
                This workspace follows one preserved source. Its recorded
                library context is historical; it does not establish current
                ownership or current library bytes.
              </p>
              {recorded.origin?.library_uuid === null && (
                <p className="context-note">
                  The recorded library identity is unavailable. This preserved
                  source remains historical; resume it from Reviews.
                </p>
              )}
              {browseReferences && (
                <button id="book-reference-browse" onClick={browseReferences}>
                  Browse reference catalogue
                </button>
              )}
              <div className="actions">
                {live(selected) && (
                  <button
                    className="cancel"
                    disabled={cancelling === selected.id}
                    onClick={() => cancel(selected)}
                  >
                    {cancelling === selected.id
                      ? "Cancelling…"
                      : "Cancel inspection"}
                  </button>
                )}
              </div>
              <div id="book-condition" className="book-section" tabIndex={-1}>
                <h2>Condition</h2>
                {selected.state === "succeeded" && (
                  <StructuralResult
                    key={`${selected.id}:${selected.source_sha256}:${selected.source_version}:${selected.result.report_sha256}`}
                    job={selected}
                    report={structuralReport}
                    showFindings={() =>
                      setFindingsRequest((previous) => ({
                        job: selected.id,
                        digest: selected.result.report_sha256,
                        sequence: (previous?.sequence ?? 0) + 1,
                      }))
                    }
                  />
                )}
                <JobProgress job={selected} announce findingsLevel={3} />
              </div>
              {selected.state === "succeeded" &&
                selected.result.report_sha256 && (
                  <EpubValidation
                    key={`validation:${selected.id}:${selected.source_sha256}:${selected.result.report_sha256}`}
                    source={selected}
                    session={session}
                    validationId={recorded.selection.fv ?? ""}
                    selectValidation={(id) => selectWorkspace({ fv: id })}
                    onJob={merge}
                    cancel={cancel}
                    cancelling={cancelling}
                    announceTerminal={announceTerminal}
                  />
                )}
              {selected.state === "succeeded" && selected.result.report_url && (
                <React.Fragment
                  key={`${selected.id}:${selected.source_sha256}:${selected.result.report_sha256}`}
                >
                  <FullReport
                    job={selected}
                    report={structuralReport}
                    findingsRequest={findingsRequest}
                  />
                  <div
                    id="book-reference"
                    className="book-section"
                    tabIndex={-1}
                  >
                    <h2>Reference</h2>
                    <PackageComparison
                      job={selected}
                      target={comparisonTarget ?? undefined}
                      clearTarget={clearComparisonTarget}
                      session={session}
                      jobs={jobs}
                      assessmentId={recorded.selection.fa ?? ""}
                      selectAssessment={(id) => selectWorkspace({ fa: id })}
                      onJob={merge}
                      cancel={cancel}
                      cancelling={cancelling}
                      announceTerminal={announceTerminal}
                    />
                  </div>
                </React.Fragment>
              )}
              {recorded.selection.fa &&
                recorded.jobs.find(
                  (job) => job.id === recorded.selection.fa,
                ) && (
                  <ResumedAssessment
                    key={recorded.selection.fa}
                    source={selected}
                    job={recorded.jobs.find(
                      (job) => job.id === recorded.selection.fa,
                    )!}
                    cancel={cancel}
                    cancelling={cancelling}
                  />
                )}
            </>
          </BookWorkspaceContext.Provider>
        </div>
      )}
    </section>
  );

  if (sessionPending && !session)
    return (
      <div className="file-inspections">
        <p role="status">Connecting to the local service…</p>
      </div>
    );
  if (!configured)
    return (
      <div className="file-inspections">
        <div className="error file-gate" role="alert">
          <p>
            {sessionError
              ? "The local service could not be reached, so EPUB uploads are unavailable."
              : "File inspection is not configured on this connection. The service has no preserved-source directory, so uploads are disabled."}
          </p>
          <p>Saved inspection history stays readable below when it exists.</p>
          <div className="actions">
            <button onClick={retrySession}>Retry connection</button>
            <button onClick={returnToReviews}>Return to reviews</button>
          </div>
        </div>
        {session && selectedSection}
        {session && !route.fj && historyView}
      </div>
    );

  const uploadSection = (
    <section
      className="file-section file-upload"
      aria-labelledby="file-upload-heading"
    >
      <h2 id="file-upload-heading">
        {selected ? "Inspect another EPUB" : "Choose an EPUB"}
      </h2>
      <p className="file-intro">
        The file is hashed in this browser, uploaded once under that digest and
        preserved unchanged by the service. The check reads archive structure
        only: it does not run EPUBCheck, identify the work, confirm ownership or
        change your library.
      </p>
      <div className="file-field">
        <label htmlFor="file-input">EPUB file</label>
        <input
          ref={input}
          id="file-input"
          type="file"
          accept=".epub,application/epub+zip"
          aria-describedby="file-limit"
          disabled={stage !== "idle"}
          onChange={choose}
        />
        <p id="file-limit" className="context-note">
          One file up to {limitLabel}. Nothing is read until you choose it.
        </p>
      </div>
      {shownName !== undefined && (
        <dl className="file-summary">
          <dt>File</dt>
          <dd className="file-name">{shownName}</dd>
          <dt>Size</dt>
          <dd>
            {shownSize !== undefined ? formatBytes(shownSize) : "Unknown"}
          </dd>
          {attempt && (
            <>
              <dt>Source digest</dt>
              <dd className="hash">{attempt.intent.digest}</dd>
              <dt>Request key</dt>
              <dd className="hash">{attempt.intent.key}</dd>
            </>
          )}
        </dl>
      )}
      {rejection && (
        <p className="error" role="alert">
          {rejection}
        </p>
      )}
      {stage !== "idle" && file && (
        <p className="file-stage" role="status">
          {stage === "hashing"
            ? `Computing the SHA-256 digest of ${file.name} in this browser…`
            : `Uploading ${file.name}… The service has up to ${UPLOAD_DEADLINE_MS / 1000} seconds to confirm. Nothing is marked queued until it answers.`}
        </p>
      )}
      {attempt?.outcome === "unconfirmed" && (
        <div className="error" role="alert">
          <p>
            The upload of {attempt.intent.name} was not confirmed:{" "}
            {attempt.reason}
          </p>
          <p>
            {attempt.recorded === "checking"
              ? "Checking whether the service recorded it…"
              : attempt.recorded === "missing"
                ? "This request is not recorded yet by the service. That is not proof the attempt was lost; a slow transfer may still be arriving."
                : "The service could not be asked whether it recorded this request."}
          </p>
          {!file && (
            <p>
              Choose the same file again to retry under the same request key, or
              check again once the service is reachable.
            </p>
          )}
          <div className="actions">
            {heldFile && (
              <button onClick={() => void inspect(false)}>Retry upload</button>
            )}
            <button
              onClick={() => {
                if (stage !== "idle") return;
                const controller = beginAttempt();
                setAttempt({ ...attempt, recorded: "checking" });
                void check(attempt.intent, controller.signal);
              }}
            >
              Check again
            </button>
            <button onClick={reset}>Choose a different file</button>
          </div>
        </div>
      )}
      {attempt?.outcome === "refused" && (
        <div className="error" role="alert">
          <p>
            The service refused this upload
            {attempt.status ? ` (${attempt.status})` : ""}: {attempt.reason}
          </p>
          <div className="actions">
            {heldFile && (
              <button onClick={() => void inspect(true)}>
                Start a new inspection
              </button>
            )}
            <button onClick={reset}>Choose a different file</button>
          </div>
        </div>
      )}
      <div className="actions">
        <button
          type="button"
          className="primary"
          disabled={!canInspect}
          onClick={() => void inspect(false)}
        >
          {stage === "hashing"
            ? "Computing digest…"
            : stage === "uploading"
              ? "Uploading…"
              : "Inspect this EPUB"}
        </button>
      </div>
    </section>
  );

  return (
    <div className="file-inspections">
      {(comparisonTarget !== undefined || returnToCatalogue) && (
        <section
          className={
            comparisonTarget === null ? "error" : "catalogue-source-comparison"
          }
          aria-label="Selected catalogue comparison"
        >
          {comparisonTarget ? (
            <p>
              A catalogue work is selected from snapshot{" "}
              {comparisonTarget.version}.{" "}
              {route.fj
                ? "Compare this preserved source explicitly against that exact selection below."
                : "Choose or inspect an EPUB below to compare it against that exact selection."}
            </p>
          ) : comparisonTarget === null ? (
            <p role="alert">
              The catalogue comparison link is incomplete or invalid. Discard it
              or return to the catalogue to choose a pinned work.
            </p>
          ) : (
            <p>Your catalogue work and browsing context remain available.</p>
          )}
          {returnToCatalogue && (
            <button onClick={returnToCatalogue}>
              Return to catalogue work
            </button>
          )}
          {comparisonTarget !== undefined && (
            <button onClick={clearComparisonTarget}>
              Discard catalogue selection
            </button>
          )}
        </section>
      )}
      {back && (
        <button className="back" onClick={back}>
          Back to file inspections
        </button>
      )}
      {!back && route.fj && history.state?.reviewOrigin && (
        <button className="back" onClick={returnToReviews}>
          Return to reviews
        </button>
      )}
      {returnToLibrary && (
        <button className="back" onClick={returnToLibrary}>
          Return to library book
        </button>
      )}
      {route.fj && (
        <button
          onClick={() =>
            navigate(
              { fj: "", ...clearWorkspace, fcw: "", fcv: "", fch: "" },
              true,
            )
          }
        >
          Choose another EPUB
        </button>
      )}
      {selectedSection}
      {!route.fj && uploadSection}
      {!route.fj && historyView}
    </div>
  );
}

function StructuralResult({
  job,
  report,
  showFindings,
}: {
  job: Job;
  report: ReturnType<typeof useStructuralReport>;
  showFindings: () => void;
}) {
  const result = job.result;
  const warnings = structuralWarnings(report.data?.report);
  const retryIntent = useRef<ReturnType<typeof trackReturnIntent> | null>(null);
  useEffect(() => () => retryIntent.current?.dispose(), []);
  async function retryWarnings() {
    retryIntent.current?.dispose();
    const intent = trackReturnIntent(
      () => {
        retryIntent.current = null;
      },
      { includeCurrentFocus: true },
    );
    retryIntent.current = intent;
    const outcome = await report.refetch();
    if (retryIntent.current !== intent) return;
    retryIntent.current = null;
    const restore = intent.isCurrent() && outcome.isSuccess;
    intent.dispose();
    if (restore)
      document.getElementById("book-condition")?.focus({ preventScroll: true });
  }
  const lead =
    result.structural_check === "passed"
      ? "The bounded structural checks passed."
      : result.structural_check === "failed"
        ? "Structural findings need attention."
        : "Structural result not recorded for this inspection.";
  const completeness =
    result.inspection_complete === true
      ? "The inspection read the whole archive."
      : result.inspection_complete === false
        ? "The inspection stopped before reading the whole archive, so the absence of further findings is not proven."
        : "";
  return (
    <section className="file-result" aria-labelledby="file-result-heading">
      <h3 id="file-result-heading">Structural result</h3>
      <p className="file-result-lead">
        {lead}
        {completeness ? ` ${completeness}` : ""}
      </p>
      {warnings?.length ? (
        <section
          className="source-warnings"
          aria-label="Recorded structural warnings"
        >
          <p>
            <strong>
              {warnings.length.toLocaleString()} recorded structural{" "}
              {warnings.length === 1 ? "warning" : "warnings"}
            </strong>
          </p>
          <ul className="structural-findings">
            {warnings.slice(0, 3).map((finding, index) => {
              const { label, note } = describeFinding(finding.code);
              return (
                <li key={index}>
                  <span className="severity severity-warning">Warning</span>
                  <strong>{label}</strong>
                  {note && <span className="finding-note">{note}</span>}
                  {finding.path ? (
                    <span className="finding-path">{finding.path}</span>
                  ) : finding.code === "missing_link_resource" ? (
                    <span className="finding-note">
                      The exact affected resource was not recorded.
                    </span>
                  ) : null}
                </li>
              );
            })}
          </ul>
          <button onClick={showFindings}>View structural findings</button>
        </section>
      ) : warnings ? (
        <p className="context-note">No structural warnings were recorded.</p>
      ) : report.data ? (
        <p className="context-note">
          Structural warning records are unavailable in this report.
        </p>
      ) : report.isError ? (
        <div className="context-note">
          <p>
            Structural warnings could not be read. {reportFailure(report.error)}
          </p>
          <button
            disabled={!report.available}
            onClick={() => void retryWarnings()}
          >
            Retry structural warnings
          </button>
        </div>
      ) : (
        <p className="context-note">
          {report.isFetching
            ? "Reading recorded structural warnings…"
            : "Structural warnings have not been read."}
        </p>
      )}
      {report.data?.report.findings_truncated && (
        <p className="context-note">
          Only recorded findings are counted; the report reached its findings
          limit.
        </p>
      )}
      {result.epubcheck === "not_run" &&
      result.content_acceptance === "not_checked" &&
      result.ready === false ? (
        <p className="file-limits">
          EPUBCheck was not run; content acceptance and readiness were not
          checked.
        </p>
      ) : (
        <ul className="file-limits">
          <li>
            {result.epubcheck === "not_run"
              ? "EPUBCheck was not run by this structural inspection."
              : result.epubcheck
                ? `EPUBCheck: ${result.epubcheck}.`
                : "EPUBCheck: not recorded."}
          </li>
          <li>
            {result.content_acceptance === "not_checked"
              ? "Content acceptance was not checked."
              : result.content_acceptance
                ? `Content acceptance: ${result.content_acceptance}.`
                : "Content acceptance: not recorded."}
          </li>
          <li>
            {result.ready === false
              ? "Readiness was not checked. This inspection cannot mark the file ready."
              : "Readiness: not recorded."}
          </li>
        </ul>
      )}
      <p className="file-limits">
        This inspection cannot identify a work, confirm ownership or approve
        library changes.
      </p>
    </section>
  );
}

type ReportState =
  | { status: "idle" }
  | { status: "loading" }
  | { status: "error"; message: string }
  | { status: "loaded"; envelope: EpubReportEnvelope };

const metadataLabels: Record<string, string> = {
  title: "Title",
  creator: "Creator",
  language: "Language",
  identifier: "Identifier",
};

class ReportBindingError extends Error {}

function reportFailure(error: unknown) {
  return error instanceof ReportBindingError
    ? error.message
    : error instanceof ApiError
      ? error.status === 409
        ? "The report is not published yet. Refresh progress and try again."
        : error.message
      : "The report could not be read. Retry when the service is reachable.";
}

function useStructuralReport(job: Job | undefined, verified: boolean) {
  const available =
    !!job && verified && job.state === "succeeded" && !!job.result.report_url;
  const query = useQuery({
    queryKey: [
      "file-structural-report",
      job?.id,
      job?.source_sha256,
      job?.source_version,
      job?.result.report_sha256,
    ],
    enabled: available,
    queryFn: async ({ signal }) => {
      if (!job || !available)
        throw new Error(
          "Verify the selected source before reading its report.",
        );
      const envelope = await fetchReport(job.id, signal);
      if (!reportBinds(job, envelope))
        throw new ReportBindingError(
          "The report returned does not match this inspection or its recorded package evidence, so it was not shown.",
        );
      if (
        envelope.report.findings !== undefined &&
        structuralWarnings(envelope.report) === undefined
      )
        throw new ReportBindingError(
          "The saved report contains unrecognized structural finding records, so they could not be shown.",
        );
      return envelope;
    },
    retry: false,
    staleTime: Infinity,
    refetchOnMount: false,
    refetchOnWindowFocus: false,
    refetchOnReconnect: false,
  });
  return { ...query, available };
}

function FullReport({
  job,
  report,
  findingsRequest,
}: {
  job: Job;
  report: ReturnType<typeof useStructuralReport>;
  findingsRequest: {
    job: string;
    digest: string | undefined;
    sequence: number;
  } | null;
}) {
  const [state, setState] = useState<ReportState>({ status: "idle" });
  const [showJson, setShowJson] = useState(false);
  const handledFindings = useRef(0);
  const focusFindings = useRef<ReturnType<typeof trackReturnIntent> | null>(
    null,
  );
  useEffect(() => {
    if (
      findingsRequest?.job !== job.id ||
      findingsRequest.digest !== job.result.report_sha256 ||
      findingsRequest.sequence <= handledFindings.current ||
      !report.data
    )
      return;
    handledFindings.current = findingsRequest.sequence;
    focusFindings.current?.dispose();
    focusFindings.current = trackReturnIntent(
      () => {
        focusFindings.current = null;
      },
      { includeCurrentFocus: true },
    );
    setState({ status: "loaded", envelope: report.data });
  }, [findingsRequest, job.id, job.result.report_sha256, report.data]);
  useEffect(() => {
    const intent = focusFindings.current;
    if (state.status !== "loaded" || !intent?.isCurrent()) return;
    intent.dispose();
    focusFindings.current = null;
    const heading = document.getElementById("report-findings");
    heading?.focus({ preventScroll: true });
    heading?.scrollIntoView({ block: "start" });
  }, [state]);
  useEffect(() => () => focusFindings.current?.dispose(), []);
  async function load() {
    setState({ status: "loading" });
    try {
      const envelope =
        report.data ?? (await report.refetch({ throwOnError: true })).data;
      if (!envelope) return;
      setState({ status: "loaded", envelope });
    } catch (error) {
      setState({
        status: "error",
        message: reportFailure(error),
      });
    }
  }
  return (
    <section className="full-report" aria-labelledby="full-report-heading">
      <h3 id="full-report-heading">Full report</h3>
      {state.status !== "loaded" && (
        <p className="context-note">
          The complete structural report is a digest-addressed record
          {typeof job.result.report_size === "number"
            ? ` of ${formatBytes(job.result.report_size)}`
            : ""}
          . Load it to read the package, identifier declarations, reading order,
          navigation and structural findings.
        </p>
      )}
      {state.status === "error" && (
        <div className="error" role="alert">
          <p>{state.message}</p>
        </div>
      )}
      {state.status !== "loaded" && (
        <div className="actions">
          <button
            className="secondary"
            disabled={state.status === "loading" || !report.available}
            onClick={() => void load()}
          >
            {state.status === "loading"
              ? "Loading the full report…"
              : state.status === "error"
                ? "Retry the full report"
                : "Load the full report"}
          </button>
        </div>
      )}
      {state.status === "loaded" && (
        <ReportBody
          envelope={state.envelope}
          showJson={showJson}
          setShowJson={setShowJson}
        />
      )}
    </section>
  );
}

type ReportDocument = NonNullable<EpubReport["documents"]>[number];

function recordedLabel(label: string | undefined): string {
  return typeof label === "string"
    ? label || "Unlabelled"
    : "Not recorded by this inspection";
}

function anchorLinks(document: ReportDocument) {
  return (document.links ?? []).filter(
    (link) => link.tag === "a" && link.attribute === "href",
  );
}

function ReportBody({
  envelope,
  showJson,
  setShowJson,
}: {
  envelope: EpubReportEnvelope;
  showJson: boolean;
  setShowJson: (value: boolean) => void;
}) {
  const report = envelope.report;
  const spine = report.spine ?? [];
  const documents = new Map(
    (report.documents ?? []).map((document) => [document.path, document]),
  );
  const chapters = (path: string) =>
    (documents.get(path)?.headings ?? [])
      .map((heading) => heading.chapter_number)
      .filter((value): value is number => typeof value === "number");
  const metadata = report.metadata ?? [];
  const navigation = report.navigation ?? {};
  const entries = navigation.entries ?? [];
  const spinePaths = new Set(spine.map((item) => item.path));
  const seenDocuments = new Set<string>();
  const contentsDocuments: ReportDocument[] = [];
  for (const document of [
    ...spine.map((item) => documents.get(item.path)),
    ...(report.documents ?? []),
  ]) {
    if (
      document &&
      !seenDocuments.has(document.path) &&
      ((document.headings ?? []).length || anchorLinks(document).length)
    ) {
      seenDocuments.add(document.path);
      contentsDocuments.push(document);
    }
  }
  const missingContentsLabels =
    contentsDocuments.some(
      (document) =>
        (document.headings ?? []).some(
          (heading) => typeof heading.label !== "string",
        ) ||
        anchorLinks(document).some(
          (link) => !link.external && typeof link.label !== "string",
        ),
    ) ||
    entries.some(
      (entry) =>
        typeof entry.label !== "string" || !Array.isArray(entry.ancestors),
    );
  const findings = report.findings ?? [];
  const upstream = report.upstream ?? {};
  return (
    <div className="report-body">
      <section className="report-part" aria-labelledby="report-package">
        <h4 id="report-package">Package</h4>
        <dl className="provenance report-facts">
          <dt>Package document</dt>
          <dd>{report.package?.path ?? "Not recorded"}</dd>
          <dt>EPUB version</dt>
          <dd>{report.package?.version ?? "Not recorded"}</dd>
          <dt>Archive members</dt>
          <dd>
            {typeof report.archive?.member_count === "number"
              ? report.archive.member_count.toLocaleString()
              : "Not recorded"}
          </dd>
          <dt>Expanded size</dt>
          <dd>
            {typeof report.archive?.expanded_bytes === "number"
              ? formatBytes(report.archive.expanded_bytes)
              : "Not recorded"}
          </dd>
          <dt>Manifest items</dt>
          <dd>
            {report.manifest
              ? report.manifest.length.toLocaleString()
              : "Not recorded"}
          </dd>
        </dl>
      </section>
      <section className="report-part" aria-labelledby="report-metadata">
        <h4 id="report-metadata">Package metadata</h4>
        {metadata.length ? (
          <dl className="provenance report-facts">
            {metadata.map((item, index) => (
              <React.Fragment key={index}>
                <dt>{metadataLabels[item.name] ?? item.name}</dt>
                <dd>{item.text || "Empty"}</dd>
              </React.Fragment>
            ))}
          </dl>
        ) : (
          <p>No title, creator, language or identifier was recorded.</p>
        )}
      </section>
      <IdentifierDeclarations report={report} />
      <SourceAttribution report={report} />
      <section className="report-part" aria-labelledby="report-order">
        <h4 id="report-order">
          Reading order{" "}
          <span className="count">
            {spine.length.toLocaleString()}{" "}
            {spine.length === 1 ? "document" : "documents"}
          </span>
        </h4>
        {spine.length ? (
          <ol className="reading-order" aria-label="Reading order">
            {spine.map((item) => {
              const numbers = chapters(item.path);
              return (
                <li key={`${item.index}-${item.idref}`}>
                  <span className="order-index">{item.index + 1}</span>
                  <span className="order-path">{item.path}</span>
                  {item.linear !== "yes" && (
                    <span className="order-note">linear {item.linear}</span>
                  )}
                  {numbers.length > 0 && (
                    <span className="order-chapter">
                      {numbers.map((number) => `Chapter ${number}`).join(", ")}
                    </span>
                  )}
                </li>
              );
            })}
          </ol>
        ) : (
          <p>The spine lists no reading order.</p>
        )}
      </section>
      <section className="report-part" aria-labelledby="report-contents">
        <h4 id="report-contents">Contents evidence</h4>
        {missingContentsLabels && (
          <p className="context-note">
            Some labels or group context were not recorded by this inspection.
            Inspect this EPUB again to capture labels and grouping.
          </p>
        )}
        {contentsDocuments.length ? (
          contentsDocuments.map((document) => {
            const links = anchorLinks(document);
            const internalLinks = links.filter(
              (link) => !link.external && typeof link.target_path === "string",
            );
            const externalCount = links.filter((link) => link.external).length;
            return (
              <div className="contents-document" key={document.path}>
                <h5>{document.path}</h5>
                {!spinePaths.has(document.path) && (
                  <p className="contents-context">Outside reading order</p>
                )}
                {(document.headings ?? []).length > 0 && (
                  <>
                    <h6 className="contents-list-heading">Headings</h6>
                    <ol
                      className="contents-items"
                      aria-label={`Headings in ${document.path}`}
                    >
                      {(document.headings ?? []).map((heading, index) => (
                        <li key={index}>
                          <span className="contents-label">
                            {recordedLabel(heading.label)}
                          </span>
                          <span className="contents-context">
                            {[
                              `Heading ${heading.level}`,
                              ...(typeof heading.chapter_number === "number"
                                ? [`Chapter ${heading.chapter_number}`]
                                : []),
                              heading.id
                                ? `#${heading.id}`
                                : "No anchor recorded",
                            ].join(" · ")}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                {internalLinks.length > 0 && (
                  <>
                    <h6 className="contents-list-heading">Links</h6>
                    <ol
                      className="contents-items"
                      aria-label={`Links in ${document.path}`}
                    >
                      {internalLinks.map((link, index) => (
                        <li key={index}>
                          <span className="contents-label">
                            {recordedLabel(link.label)}
                          </span>
                          <span className="contents-target">
                            {link.target_path}
                            {link.fragment ? `#${link.fragment}` : ""}
                          </span>
                        </li>
                      ))}
                    </ol>
                  </>
                )}
                {externalCount > 0 && (
                  <p className="contents-context">
                    {externalCount.toLocaleString()} external{" "}
                    {externalCount === 1
                      ? "link is omitted"
                      : "links are omitted"}{" "}
                    from this view.
                  </p>
                )}
              </div>
            );
          })
        ) : (
          <p>No headings or anchor links were recorded.</p>
        )}
      </section>
      <section className="report-part" aria-labelledby="report-navigation">
        <h4 id="report-navigation">Navigation</h4>
        <dl className="provenance report-facts">
          <dt>Navigation documents</dt>
          <dd>
            {navigation.nav_paths?.length
              ? navigation.nav_paths.join(", ")
              : "None recorded"}
          </dd>
          <dt>NCX documents</dt>
          <dd>
            {navigation.ncx_paths?.length
              ? navigation.ncx_paths.join(", ")
              : "None recorded"}
          </dd>
          <dt>External links</dt>
          <dd>
            {typeof navigation.external_link_count === "number"
              ? navigation.external_link_count.toLocaleString()
              : "Not recorded"}
          </dd>
        </dl>
        {entries.length ? (
          <details className="report-entries">
            <summary>
              {entries.length.toLocaleString()} navigation{" "}
              {entries.length === 1 ? "entry" : "entries"}
            </summary>
            <ol className="contents-items">
              {entries.map((entry, index) => (
                <li key={index}>
                  <span className="contents-label">
                    {recordedLabel(entry.label)}
                  </span>
                  <span className="contents-context">
                    {Array.isArray(entry.ancestors)
                      ? entry.ancestors.length
                        ? `Within: ${entry.ancestors.map((label) => label || "Unlabelled group").join(" / ")}`
                        : "Top level"
                      : "Grouping: Not recorded by this inspection"}
                  </span>
                  <span className="contents-target">
                    {entry.target_path}
                    {entry.fragment ? `#${entry.fragment}` : ""}
                  </span>
                  <span className="contents-context">
                    {entry.kind === "nav"
                      ? "NAV"
                      : entry.kind === "ncx"
                        ? "NCX"
                        : "Navigation"}{" "}
                    · {entry.path}
                  </span>
                </li>
              ))}
            </ol>
          </details>
        ) : (
          <p>No navigation entries were recorded.</p>
        )}
      </section>
      <section className="report-part" aria-labelledby="report-findings">
        <h4 id="report-findings" tabIndex={-1}>
          Structural findings{" "}
          <span className="count">{findings.length.toLocaleString()}</span>
        </h4>
        {findings.length ? (
          <ul className="structural-findings">
            {findings.map((finding, index) => {
              const { label, note } = describeFinding(finding.code);
              return (
                <li key={index}>
                  <span className={`severity severity-${finding.severity}`}>
                    {finding.severity === "error"
                      ? "Error"
                      : finding.severity === "warning"
                        ? "Warning"
                        : finding.severity}
                  </span>
                  <strong>{label}</strong>
                  {finding.path && (
                    <span className="finding-path">{finding.path}</span>
                  )}
                  {note && <span className="finding-note">{note}</span>}
                </li>
              );
            })}
          </ul>
        ) : (
          <p>No structural findings were recorded.</p>
        )}
        {report.inspection_complete === false && (
          <p className="context-note">
            Inspection was incomplete; further structural problems may remain.
          </p>
        )}
        {report.inspection_complete === undefined && (
          <p className="context-note">
            Inspection coverage was not recorded in this report.
          </p>
        )}
        {report.findings_truncated && (
          <p className="context-note">
            The findings list reached its budget; later findings were not
            recorded.
          </p>
        )}
      </section>
      <section className="report-part" aria-labelledby="report-provenance">
        <h4 id="report-provenance">Report provenance</h4>
        <dl className="provenance">
          <dt>Report digest</dt>
          <dd className="hash">{envelope.report_sha256}</dd>
          <dt>Schema</dt>
          <dd>{report.schema_version ?? "Not recorded"}</dd>
          <dt>Policy</dt>
          <dd>{report.policy?.version ?? "Not recorded"}</dd>
          <dt>Inspector source</dt>
          <dd>
            {upstream.source ?? "Not recorded"}
            {upstream.revision ? ` at ${upstream.revision}` : ""}
          </dd>
          <dt>Inspector source digest</dt>
          <dd className="hash">{upstream.source_sha256 ?? "Not recorded"}</dd>
          <dt>Repository</dt>
          <dd>{upstream.repository ?? "Not recorded"}</dd>
        </dl>
      </section>
      <details
        className="report-json"
        onToggle={(event) => setShowJson(event.currentTarget.open)}
      >
        <summary>Raw report JSON</summary>
        {showJson && (
          <pre
            tabIndex={0}
            role="region"
            aria-label="Raw structural report JSON"
          >
            {JSON.stringify(report, null, 2)}
          </pre>
        )}
      </details>
    </div>
  );
}
