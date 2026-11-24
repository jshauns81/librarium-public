import React, { useEffect, useRef, useState } from "react";
import {
  keepPreviousData,
  useQuery,
  useQueryClient,
} from "@tanstack/react-query";
import { ApiError } from "./api";
import { JobProgress } from "./JobProgress";
import { EpubCheckMessage } from "./EpubCheckMessage";
import { useBookWorkspace } from "./book-workspace";
import type {
  EpubValidationCounts,
  EpubValidationEnvelope,
  Job,
  Session,
} from "./types";
import {
  clearValidationIntent,
  makeValidationIntent,
  readValidation,
  readValidationHistory,
  readValidationIntent,
  readValidationReport,
  recoverValidation,
  requestValidation,
  saveValidationIntent,
  validationSummaryBinds,
  type ValidationIntent,
} from "./epub-validation-api";
import "./epub-validation.css";

const active = (job: Job) => ["queued", "running"].includes(job.state);
type Attempt = {
  intent: ValidationIntent;
  outcome: "pending" | "unconfirmed" | "refused";
  reason: string;
};
const newer = (left: Job | undefined, right: Job | undefined) =>
  left && right
    ? left.revision >= right.revision
      ? left
      : right
    : (left ?? right);

function Counts({ counts }: { counts: EpubValidationCounts }) {
  return (
    <dl className="validation-counts" aria-label="EPUBCheck diagnostic counts">
      {(["fatal", "error", "warning", "info", "usage"] as const).map(
        (severity) => (
          <React.Fragment key={severity}>
            <dt>{severity[0].toUpperCase() + severity.slice(1)}</dt>
            <dd>
              {counts[severity] === null
                ? "Not reported"
                : counts[severity].toLocaleString()}
            </dd>
          </React.Fragment>
        ),
      )}
    </dl>
  );
}

function ValidationReport({ source, job }: { source: Job; job: Job }) {
  const [state, setState] = useState<
    | { status: "idle" | "loading" | "error"; message?: string }
    | { status: "loaded"; value: EpubValidationEnvelope }
  >({ status: "idle" });
  const request = useRef<AbortController | null>(null);
  const trigger = useRef<HTMLButtonElement>(null);
  const heading = useRef<HTMLHeadingElement>(null);
  const focusReport = useRef(false);
  useEffect(() => () => request.current?.abort(), []);
  useEffect(() => {
    if (state.status === "loaded" && focusReport.current) {
      focusReport.current = false;
      heading.current?.focus({ preventScroll: true });
    }
  }, [state.status]);
  async function load() {
    request.current?.abort();
    const controller = new AbortController();
    request.current = controller;
    setState({ status: "loading" });
    try {
      const value = await readValidationReport(source, job, controller.signal);
      if (!controller.signal.aborted) {
        focusReport.current = document.activeElement === trigger.current;
        setState({ status: "loaded", value });
      }
    } catch (error) {
      if (!controller.signal.aborted)
        setState({
          status: "error",
          message:
            error instanceof Error
              ? error.message
              : "The diagnostics could not be read.",
        });
    }
  }
  if (state.status !== "loaded")
    return (
      <div className="validation-report">
        {state.status === "error" && (
          <p className="error" role="alert">
            {state.message}
          </p>
        )}
        <button
          ref={trigger}
          className="secondary"
          aria-disabled={state.status === "loading"}
          onClick={() => {
            if (state.status !== "loading") void load();
          }}
        >
          {state.status === "loading"
            ? "Loading EPUBCheck diagnostics…"
            : state.status === "error"
              ? "Retry EPUBCheck diagnostics"
              : "Load EPUBCheck diagnostics"}
        </button>
      </div>
    );
  const report = state.value.report;
  return (
    <section
      className="validation-diagnostics"
      aria-labelledby="validation-diagnostics-heading"
    >
      <h5 ref={heading} tabIndex={-1} id="validation-diagnostics-heading">
        EPUBCheck diagnostics
      </h5>
      {report.messages_truncated && (
        <p className="validation-limit">
          Some diagnostics or source locations were omitted by the report
          limits. Checker counts are retained.
        </p>
      )}
      <p className="context-note">
        Repeated diagnostics are limited to{" "}
        {report.message_repetition_limit.toLocaleString()} for each diagnostic
        ID and message text.
      </p>
      {report.messages.length ? (
        <ol className="validation-messages">
          {report.messages.map((message, index) => (
            <li key={index}>
              <p
                className={`validation-message-label severity-${message.severity.toLowerCase()}`}
              >
                <strong>{message.severity}</strong> · {message.id}
              </p>
              <EpubCheckMessage
                id={message.id}
                message={message.message}
                className="validation-message-text"
              />
              {message.locations.length > 0 && (
                <ul
                  className="validation-locations"
                  aria-label={`Locations for ${message.id}`}
                >
                  {message.locations.map((location, position) => (
                    <li key={position}>
                      {(location.path || "Publication") +
                        (location.line === null
                          ? ""
                          : ` · line ${location.line}`) +
                        (location.column === null
                          ? ""
                          : ` · column ${location.column}`)}
                    </li>
                  ))}
                </ul>
              )}
            </li>
          ))}
        </ol>
      ) : (
        <p>No diagnostic messages were retained in this report.</p>
      )}
      {report.limitations.length > 0 && (
        <div className="validation-scope">
          <h5>Scope of this validation</h5>
          <ul>
            {report.limitations.map((value, index) => (
              <li key={index}>{value}</li>
            ))}
          </ul>
        </div>
      )}
      <details className="validation-provenance">
        <summary>Diagnostic report provenance</summary>
        <dl className="provenance">
          <dt>Validation job</dt>
          <dd className="hash">{state.value.job_id}</dd>
          <dt>Source inspection</dt>
          <dd className="hash">{state.value.source_job_id}</dd>
          <dt>Source digest</dt>
          <dd className="hash">{state.value.source_sha256}</dd>
          <dt>Source structural report digest</dt>
          <dd className="hash">{state.value.source_report_sha256}</dd>
          <dt>Validation report digest</dt>
          <dd className="hash">{state.value.report_sha256}</dd>
          <dt>Preserved source bytes</dt>
          <dd>{report.source_size.toLocaleString()}</dd>
          <dt>Checker</dt>
          <dd>
            {report.validator.name} {report.validator.version}
          </dd>
          <dt>Distribution digest</dt>
          <dd className="hash">{report.validator.distribution_sha256}</dd>
          <dt>JAR manifest digest</dt>
          <dd className="hash">{report.validator.jar_manifest_sha256}</dd>
          <dt>Java major</dt>
          <dd>{report.validator.java_major}</dd>
          <dt>Policy</dt>
          <dd>{report.policy.version}</dd>
          <dt>Process exit code</dt>
          <dd>{report.process_exit_code}</dd>
        </dl>
      </details>
    </section>
  );
}

export function EpubValidation({
  source,
  session,
  validationId = "",
  selectValidation,
  onJob,
  cancel,
  cancelling,
  announceTerminal,
}: {
  source: Job;
  session: Session | undefined;
  validationId?: string;
  selectValidation: (id: string) => void;
  onJob: (job: Job) => void;
  cancel: (job: Job) => void;
  cancelling?: string;
  announceTerminal: (jobs: Job[]) => void;
}) {
  const client = useQueryClient();
  const [page, setPage] = useState(1);
  const [discoveredId, setDiscoveredId] = useState("");
  const [attempt, setAttempt] = useState<Attempt | null>(() => {
    const intent = readValidationIntent(source);
    return intent
      ? {
          intent,
          outcome: "unconfirmed",
          reason:
            "This page was closed or reloaded before the request was confirmed.",
        }
      : null;
  });
  const initialIntent = useRef(attempt?.intent);
  const recovered = useRef(false);
  const operation = useRef<AbortController | null>(null);
  const busy = useRef(false);
  const [working, setWorking] = useState<"idle" | "starting" | "recovering">(
    "idle",
  );
  const [storageUnavailable, setStorageUnavailable] = useState(false);
  const callbacks = useRef({ onJob, selectValidation, announceTerminal });
  callbacks.current = { onJob, selectValidation, announceTerminal };
  const currentSelection = useRef(validationId);
  currentSelection.current = validationId;
  const previousSelection = useRef(validationId);
  const selectedHeading = useRef<HTMLHeadingElement>(null);
  const focusSelected = useRef(false);
  const historySummary = useRef<HTMLParagraphElement>(null);
  const focusHistory = useRef(false);
  const workspace = useBookWorkspace();
  const configured = session?.epub_validation === true;
  const readable =
    typeof session?.epub_validation === "boolean" || !!validationId;
  const selectedId = validationId || discoveredId;

  const history = useQuery({
    queryKey: ["epub-validation-history", source.id, page],
    enabled: readable,
    queryFn: ({ signal }) => readValidationHistory(source, page, signal),
    placeholderData: keepPreviousData,
    retry: false,
    refetchInterval: (query) =>
      query.state.data?.jobs.some(active) || attempt?.outcome === "unconfirmed"
        ? 1500
        : false,
  });
  const detail = useQuery({
    queryKey: ["epub-validation-job", source.id, selectedId],
    enabled: readable && !!selectedId,
    queryFn: ({ signal }) => readValidation(source, selectedId, signal),
    retry: false,
    refetchInterval: (query) =>
      query.state.data && active(query.state.data) ? 1500 : false,
    structuralSharing: (old, incoming) =>
      newer(old as Job | undefined, incoming as Job)!,
  });
  const savedHistory = useRef<typeof history.data>(undefined);
  if (history.data && !history.isPlaceholderData)
    savedHistory.current = history.data;
  const visibleHistory = history.data ?? savedHistory.current;
  const selected = newer(
    visibleHistory?.jobs.find((job) => job.id === selectedId),
    detail.data?.id === selectedId ? detail.data : undefined,
  );
  const hasActive =
    visibleHistory?.jobs.some(active) || (!!selected && active(selected));

  function begin(stage: "starting" | "recovering") {
    operation.current?.abort();
    const controller = new AbortController();
    operation.current = controller;
    busy.current = true;
    setWorking(stage);
    return controller;
  }
  function finish(controller: AbortController) {
    if (operation.current !== controller) return;
    operation.current = null;
    busy.current = false;
    setWorking("idle");
  }
  function confirm(job: Job, signal: AbortSignal, automatic: boolean) {
    if (
      signal.aborted ||
      (automatic &&
        currentSelection.current &&
        currentSelection.current !== job.id)
    )
      return;
    clearValidationIntent(source, job.request_key);
    setAttempt(null);
    client.setQueryData<Job>(
      ["epub-validation-job", source.id, job.id],
      (previous) => newer(previous, job)!,
    );
    callbacks.current.onJob(job);
    setDiscoveredId(job.id);
    previousSelection.current = job.id;
    focusSelected.current = true;
    callbacks.current.selectValidation(job.id);
    void client.invalidateQueries({
      queryKey: ["epub-validation-history", source.id],
    });
  }
  async function lookup(
    intent: ValidationIntent,
    controller: AbortController,
    automatic: boolean,
  ) {
    try {
      const job = await recoverValidation(
        source,
        intent.key,
        controller.signal,
      );
      confirm(job, controller.signal, automatic);
    } catch (error) {
      if (controller.signal.aborted) return;
      const refused = error instanceof ApiError && error.status === 409;
      if (refused) clearValidationIntent(source, intent.key);
      setAttempt({
        intent,
        outcome: refused ? "refused" : "unconfirmed",
        reason:
          error instanceof ApiError && error.status === 404
            ? "The request is not recorded yet."
            : error instanceof Error
              ? error.message
              : "The request status could not be confirmed.",
      });
    }
  }
  async function checkRequest() {
    if (!attempt || busy.current) return;
    const controller = begin("recovering");
    await lookup(attempt.intent, controller, false);
    finish(controller);
  }
  async function start(retry = false) {
    if (workspace?.ready === false) return;
    if (!session || !configured || busy.current || hasActive) return;
    const intent =
      retry && attempt ? attempt.intent : makeValidationIntent(source);
    setStorageUnavailable(!saveValidationIntent(intent));
    const controller = begin("starting");
    setAttempt({ intent, outcome: "pending", reason: "" });
    try {
      const job = await requestValidation(
        source,
        intent.key,
        session.csrf,
        controller.signal,
      );
      confirm(job, controller.signal, false);
    } catch (error) {
      if (controller.signal.aborted) return;
      const refused =
        error instanceof ApiError && error.status < 500 && error.status !== 408;
      if (refused) {
        clearValidationIntent(source, intent.key);
        setAttempt({ intent, outcome: "refused", reason: error.message });
      } else {
        setAttempt({
          intent,
          outcome: "unconfirmed",
          reason:
            "The service did not confirm whether this EPUBCheck was queued.",
        });
        setWorking("recovering");
        await lookup(intent, controller, false);
      }
    } finally {
      finish(controller);
    }
  }
  function open(job: Job) {
    operation.current?.abort();
    operation.current = null;
    busy.current = false;
    setWorking("idle");
    setAttempt((previous) =>
      previous?.outcome === "pending"
        ? {
            ...previous,
            outcome: "unconfirmed",
            reason: "Selection changed before the request was confirmed.",
          }
        : previous,
    );
    focusSelected.current = true;
    callbacks.current.selectValidation(job.id);
  }
  useEffect(() => () => operation.current?.abort(), []);
  useEffect(() => {
    if (previousSelection.current === validationId) return;
    previousSelection.current = validationId;
    operation.current?.abort();
    operation.current = null;
    busy.current = false;
    setWorking("idle");
    setAttempt((previous) =>
      previous?.outcome === "pending"
        ? {
            ...previous,
            outcome: "unconfirmed",
            reason: "Selection changed before the request was confirmed.",
          }
        : previous,
    );
  }, [validationId]);
  useEffect(() => {
    if (
      !readable ||
      recovered.current ||
      !initialIntent.current ||
      validationId
    )
      return;
    recovered.current = true;
    const controller = begin("recovering");
    void lookup(initialIntent.current, controller, true).finally(() =>
      finish(controller),
    );
  }, [readable, validationId]);
  useEffect(() => {
    if (!visibleHistory || history.isPlaceholderData) return;
    if (
      attempt?.outcome === "unconfirmed" &&
      !currentSelection.current &&
      !operation.current
    ) {
      const matched = visibleHistory.jobs.find(
        (job) => job.request_key === attempt.intent.key,
      );
      if (matched) confirm(matched, new AbortController().signal, true);
    }
    if (!validationId && !discoveredId && !attempt && visibleHistory.jobs[0])
      setDiscoveredId(visibleHistory.jobs[0].id);
  }, [
    visibleHistory,
    history.isPlaceholderData,
    validationId,
    discoveredId,
    attempt,
  ]);
  useEffect(() => {
    if (selected) {
      callbacks.current.onJob(selected);
      callbacks.current.announceTerminal([selected]);
    }
  }, [selected?.id, selected?.revision]);
  useEffect(() => {
    if (selected && focusSelected.current) {
      focusSelected.current = false;
      requestAnimationFrame(() =>
        selectedHeading.current?.focus({ preventScroll: true }),
      );
    }
  }, [selected?.id]);
  useEffect(() => {
    if (
      !focusHistory.current ||
      history.isFetching ||
      history.isPlaceholderData
    )
      return;
    focusHistory.current = false;
    historySummary.current?.focus({ preventScroll: true });
  }, [history.isFetching, history.isPlaceholderData, visibleHistory]);

  const pages = Math.max(1, Math.ceil((visibleHistory?.total ?? 0) / 20));
  const summaryVerified =
    !!selected && validationSummaryBinds(source, selected);
  return (
    <section className="epub-validation" aria-labelledby="epubcheck-heading">
      <h3 id="epubcheck-heading">EPUBCheck</h3>
      <p className="validation-intro">
        Run a separate conformance check of this preserved EPUB. The structural
        report and source file remain unchanged. Content acceptance and
        readiness are separate checks.
      </p>
      {!configured && (
        <p className="context-note">
          This connection cannot start EPUBCheck. Saved validation attempts
          remain readable when available.
        </p>
      )}
      {configured && (
        <div className="actions">
          {!attempt && (
            <button
              className="secondary"
              aria-disabled={working !== "idle" || hasActive}
              onClick={() => void start()}
            >
              {working === "starting" ? "Starting EPUBCheck…" : "Run EPUBCheck"}
            </button>
          )}
          {session?.epub_validator && (
            <span className="validation-profile">
              For a new check: {session.epub_validator.name}{" "}
              {session.epub_validator.version}
            </span>
          )}
        </div>
      )}
      {working !== "idle" && (
        <p role="status">
          {working === "starting"
            ? "Requesting EPUBCheck…"
            : "Checking the saved request status…"}
        </p>
      )}
      {storageUnavailable && (
        <p className="context-note">
          Browser storage is unavailable. Keep this page open to recover an
          unconfirmed request.
        </p>
      )}
      {attempt?.outcome === "unconfirmed" && (
        <div className="error" role="alert">
          <p>The EPUBCheck request was not confirmed. {attempt.reason}</p>
          <div className="actions">
            <button
              aria-disabled={working !== "idle"}
              onClick={() => void checkRequest()}
            >
              Check EPUBCheck request status
            </button>
            {configured && (
              <button
                aria-disabled={working !== "idle"}
                onClick={() => void start(true)}
              >
                Retry this EPUBCheck request
              </button>
            )}
          </div>
        </div>
      )}
      {attempt?.outcome === "refused" && (
        <div className="error" role="alert">
          <p>{attempt.reason}</p>
          {configured && (
            <button
              aria-disabled={working !== "idle" || hasActive}
              onClick={() => void start()}
            >
              Start a new EPUBCheck
            </button>
          )}
        </div>
      )}
      {selected ? (
        <section
          className="validation-selected"
          aria-labelledby="validation-attempt-heading"
        >
          <h4
            ref={selectedHeading}
            tabIndex={-1}
            id="validation-attempt-heading"
          >
            EPUBCheck attempt
          </h4>
          <p className="validation-profile">
            Captured checker: {selected.validator?.name}{" "}
            {selected.validator?.version}
          </p>
          {detail.isError && (
            <div className="error" role="alert">
              <p>
                EPUBCheck status could not be refreshed. The previous state
                remains visible.
              </p>
              <p>{detail.error.message}</p>
              <button onClick={() => void detail.refetch()}>
                Retry EPUBCheck status
              </button>
            </div>
          )}
          {(selected.state !== "succeeded" || summaryVerified) && (
            <JobProgress job={selected} />
          )}
          {active(selected) && (
            <button
              className="cancel"
              aria-disabled={cancelling === selected.id}
              onClick={() => {
                if (cancelling !== selected.id) cancel(selected);
              }}
            >
              {cancelling === selected.id ? "Cancelling…" : "Cancel EPUBCheck"}
            </button>
          )}
          {selected.state === "succeeded" &&
            (summaryVerified ? (
              <div className="validation-outcome">
                <p
                  className={
                    selected.result.outcome === "failed"
                      ? "validation-failed"
                      : "validation-passed"
                  }
                >
                  {selected.result.outcome === "passed"
                    ? "EPUBCheck passed"
                    : "EPUBCheck found conformance errors"}
                </p>
                <Counts counts={selected.result.counts!} />
                <p className="context-note">
                  Content acceptance was not checked. This validation does not
                  mark the file ready.
                </p>
                <ValidationReport
                  key={`${selected.id}:${selected.result.report_sha256}`}
                  source={source}
                  job={selected}
                />
              </div>
            ) : (
              <p className="error" role="alert">
                The saved EPUBCheck outcome could not be verified against this
                source and its captured profile.
              </p>
            ))}
          <details className="validation-provenance">
            <summary>Captured validation profile</summary>
            <dl className="provenance">
              <dt>Source inspection</dt>
              <dd className="hash">{selected.source_job_id}</dd>
              <dt>Source structural report digest</dt>
              <dd className="hash">{selected.source_report_sha256}</dd>
              <dt>Checker</dt>
              <dd>
                {selected.validator?.name} {selected.validator?.version}
              </dd>
              <dt>Distribution digest</dt>
              <dd className="hash">
                {selected.validator?.distribution_sha256}
              </dd>
              <dt>JAR manifest digest</dt>
              <dd className="hash">
                {selected.validator?.jar_manifest_sha256}
              </dd>
              <dt>Policy</dt>
              <dd>{selected.policy?.version}</dd>
            </dl>
          </details>
        </section>
      ) : detail.isError ? (
        <div className="error" role="alert">
          <p>{detail.error.message}</p>
          <button onClick={() => void detail.refetch()}>
            Retry EPUBCheck status
          </button>
        </div>
      ) : selectedId ? (
        <p role="status">Reading EPUBCheck status…</p>
      ) : null}
      {readable && (
        <section
          className="validation-history"
          aria-labelledby="validation-history-heading"
        >
          <h4 id="validation-history-heading">Previous EPUBCheck attempts</h4>
          <p
            ref={historySummary}
            tabIndex={-1}
            className="context-note"
            role="status"
          >
            {history.isFetching &&
            (!visibleHistory || history.isPlaceholderData)
              ? "Loading EPUBCheck history…"
              : history.isError
                ? "EPUBCheck history could not be refreshed."
                : visibleHistory?.total
                  ? `${visibleHistory.total.toLocaleString()} EPUBCheck ${visibleHistory.total === 1 ? "attempt" : "attempts"}`
                  : "No EPUBCheck attempts recorded."}
          </p>
          {history.isError && (
            <div className="error" role="alert">
              <p>{history.error.message}</p>
              <button
                aria-disabled={history.isFetching}
                onClick={() => {
                  if (!history.isFetching) void history.refetch();
                }}
              >
                Retry EPUBCheck history
              </button>
            </div>
          )}
          {visibleHistory?.jobs.length ? (
            <ol className="validation-history-list">
              {visibleHistory.jobs.map((job) => (
                <li key={job.id}>
                  <button
                    className="text-button"
                    aria-current={selected?.id === job.id ? "true" : undefined}
                    aria-label={`Open EPUBCheck updated ${new Date(job.updated_at).toLocaleString()}`}
                    onClick={() => open(job)}
                  >
                    <time dateTime={job.updated_at}>
                      {new Date(job.updated_at).toLocaleString()}
                    </time>
                  </button>
                  <span>
                    {job.state === "succeeded"
                      ? "Complete"
                      : job.state === "failed"
                        ? "Execution failed"
                        : job.state === "running"
                          ? "Running"
                          : job.state === "cancelled"
                            ? "Cancelled"
                            : "Queued"}
                  </span>
                  <span>
                    {job.validator?.name} {job.validator?.version}
                  </span>
                </li>
              ))}
            </ol>
          ) : null}
          {pages > 1 && (
            <nav className="pagination" aria-label="EPUBCheck history pages">
              <button
                disabled={page === 1}
                aria-disabled={history.isFetching || history.isPlaceholderData}
                onClick={() => {
                  if (!history.isFetching && !history.isPlaceholderData) {
                    focusHistory.current = true;
                    setPage((value) => Math.max(1, value - 1));
                  }
                }}
              >
                Previous EPUBCheck page
              </button>
              <span>
                Page {visibleHistory?.page ?? page} of {pages}
              </span>
              <button
                disabled={page >= pages}
                aria-disabled={history.isFetching || history.isPlaceholderData}
                onClick={() => {
                  if (!history.isFetching && !history.isPlaceholderData) {
                    focusHistory.current = true;
                    setPage((value) => value + 1);
                  }
                }}
              >
                Next EPUBCheck page
              </button>
            </nav>
          )}
        </section>
      )}
      {readable && (
        <div className="actions">
          <button
            onClick={() => {
              void history.refetch();
              if (selectedId) void detail.refetch();
            }}
          >
            Refresh EPUBCheck status
          </button>
        </div>
      )}
    </section>
  );
}
