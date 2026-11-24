import React, { useEffect, useRef } from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import "./catalogue-control.css";

type Pin = { version: string; sha256: string; fixture: boolean };
type Queue = "incomplete" | "conflicts" | "possible_duplicates";
export type CatalogueControlRoute = {
  cv: string;
  ch: string;
  cc: string;
  ccp: number;
};
type Control = {
  snapshot: Pin;
  producer: {
    status: string;
    message: string;
    current?: Pin | null;
    last_outcome?: {
      request_key: string;
      completed_at: string | null;
      state: "preparing" | "succeeded" | "failed" | "prepared";
      source: string;
      records: number;
      version: string;
      sha256: string | null;
      message?: string | null;
      error_code?: string | null;
    } | null;
  };
  source_observations: {
    source: string;
    last_recorded_at: string | null;
    last_recorded_status: string | null;
    live: false;
  }[];
  counts: {
    incomplete: number;
    conflicts: number;
    possible_duplicates: number;
    unmatched: number | null;
  };
  library_matching: { status: string; message: string };
  queue: Queue;
  page: number;
  pages: number;
  page_size: number;
  total: number;
  works: { id: string; title: string; reasons: string[] }[];
  scope: string;
};
const labels: Record<Queue, string> = {
  incomplete: "Incomplete records",
  conflicts: "Conflicting records",
  possible_duplicates: "Possible duplicates",
};
export function CatalogueControl({
  route,
  navigate,
}: {
  route: CatalogueControlRoute;
  navigate: (
    next: Partial<CatalogueControlRoute> & {
      cm?: string;
      cb?: string;
      cw?: string;
      cp?: number;
      cq?: string;
      cs?: string;
      ca?: string;
    },
    push?: boolean,
  ) => void;
}) {
  const status = useQuery({
    queryKey: ["catalogue-status"],
    queryFn: ({ signal }) =>
      api<
        | ({ status: "ready"; total: number } & Pin)
        | { status: "not_configured" }
      >("catalogue", { signal }),
    retry: false,
  });
  const available = status.data?.status === "ready" ? status.data : undefined;
  const version = route.cv || available?.version || "";
  const sha256 = route.ch || available?.sha256 || "";
  const queue: Queue = Object.hasOwn(labels, route.cc)
    ? (route.cc as Queue)
    : "incomplete";
  const summary = useRef<HTMLParagraphElement>(null);
  const focusResults = useRef(false);
  const report = useQuery({
    queryKey: ["catalogue-control", version, sha256, queue, route.ccp],
    enabled: !!version && !!sha256,
    queryFn: ({ signal }) =>
      api<Control>(
        `catalogue/control?${new URLSearchParams({ version, sha256, queue, page: String(route.ccp) })}`,
        { signal },
      ),
    retry: false,
  });
  useEffect(() => {
    if (focusResults.current && report.data && !report.isFetching) {
      summary.current?.focus();
      focusResults.current = false;
    }
  }, [report.data, report.isFetching]);
  function browse(work = "") {
    navigate(
      {
        cm: "browse",
        cw: work,
        ...(work ? { cb: "works" } : {}),
        cv: version,
        ch: sha256,
        cp: 1,
        cq: "",
        cs: "",
        ca: "",
      },
      true,
    );
  }
  const error = status.error || report.error;
  return (
    <section className="catalogue-control" aria-label="Catalogue control">
      <header className="catalogue-control-heading">
        <div>
          <h1>Catalogue control</h1>
          <p>
            Reference records, source observations and the work that needs
            attention.
          </p>
        </div>
        <button onClick={() => browse()}>Browse catalogue</button>
      </header>
      {status.isPending && <p role="status">Reading catalogue status…</p>}
      {status.data?.status === "not_configured" && (
        <p>
          No reference catalogue is configured. Library browsing remains
          available.
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          <p>Catalogue control could not be read: {error.message}</p>
          <button
            onClick={() => {
              void status.refetch();
              void report.refetch();
            }}
          >
            Retry catalogue control
          </button>
          {available &&
            (available.version !== version || available.sha256 !== sha256) && (
              <button
                onClick={() =>
                  navigate(
                    { cv: available.version, ch: available.sha256, ccp: 1 },
                    true,
                  )
                }
              >
                Use current snapshot
              </button>
            )}
        </div>
      )}
      {report.data && !report.isError && (
        <>
          <section
            className="catalogue-update"
            aria-labelledby="catalogue-update-title"
          >
            <h2 id="catalogue-update-title">Reference updates</h2>
            <p>{report.data.producer.message}</p>
            {report.data.producer.last_outcome && (
              <div role="group" aria-label="Last reference import">
                <h3>Last import</h3>
                <dl className="catalogue-source-observations">
                  <dt>Outcome</dt>
                  <dd>
                    {
                      {
                        succeeded: "Completed",
                        failed: "Failed",
                        prepared: "Prepared",
                        preparing: "Preparing",
                      }[report.data.producer.last_outcome.state]
                    }
                  </dd>
                  <dt>Source</dt>
                  <dd>{report.data.producer.last_outcome.source}</dd>
                  <dt>Records</dt>
                  <dd>
                    {report.data.producer.last_outcome.records.toLocaleString()}
                  </dd>
                  <dt>Publication</dt>
                  <dd>
                    {report.data.producer.last_outcome.version ||
                      "Not published"}
                  </dd>
                  <dt>Completed</dt>
                  <dd>
                    {report.data.producer.last_outcome.completed_at ? (
                      <time
                        dateTime={
                          report.data.producer.last_outcome.completed_at
                        }
                      >
                        {new Date(
                          report.data.producer.last_outcome.completed_at,
                        ).toLocaleString()}
                      </time>
                    ) : (
                      "Not recorded"
                    )}
                  </dd>
                </dl>
                {report.data.producer.last_outcome.message && (
                  <p>{report.data.producer.last_outcome.message}</p>
                )}
              </div>
            )}
            {report.data.producer.current && (
              <p>
                Latest native publication:{" "}
                {report.data.producer.current.version}
                {report.data.producer.current.fixture
                  ? " · Fictional test data"
                  : ""}
                .
                {(report.data.producer.current.version !== version ||
                  report.data.producer.current.sha256 !== sha256) &&
                  " This view uses a different snapshot."}
              </p>
            )}
            {report.data.producer.status !== "not_configured" && (
              <button
                aria-busy={report.isFetching}
                onClick={() => {
                  void status.refetch();
                  void report.refetch();
                }}
              >
                {report.isFetching
                  ? "Reading update status…"
                  : "Refresh update status"}
              </button>
            )}
            <p className="catalogue-control-context">
              Snapshot {report.data.snapshot.version}
              {report.data.snapshot.fixture ? " · Fictional test data" : ""}.
              Source observations describe this saved snapshot; they do not
              confirm that an updater is running.
            </p>
            {available &&
              (available.version !== version ||
                available.sha256 !== sha256) && (
                <button
                  onClick={() =>
                    navigate(
                      { cv: available.version, ch: available.sha256, ccp: 1 },
                      true,
                    )
                  }
                >
                  Use current snapshot
                </button>
              )}
            {report.data.source_observations.length > 0 ? (
              <dl className="catalogue-source-observations">
                {report.data.source_observations.map((source, index) => (
                  <React.Fragment key={`${source.source}:${index}`}>
                    <dt>{source.source}</dt>
                    <dd>
                      {source.last_recorded_status || "Status not recorded"} ·{" "}
                      {source.last_recorded_at || "Date not recorded"}
                    </dd>
                  </React.Fragment>
                ))}
              </dl>
            ) : (
              <p>No source update observations are recorded.</p>
            )}
          </section>
          <section aria-label="Catalogue attention queues">
            <h2>Needs attention</h2>
            <div
              className="catalogue-queue-options"
              role="group"
              aria-label="Attention queue"
            >
              {(Object.keys(labels) as Queue[]).map((value) => (
                <button
                  key={value}
                  aria-pressed={queue === value}
                  onClick={() => {
                    focusResults.current = true;
                    navigate(
                      { cc: value, ccp: 1, cv: version, ch: sha256 },
                      true,
                    );
                  }}
                >
                  {labels[value]}{" "}
                  <span>{report.data!.counts[value].toLocaleString()}</span>
                </button>
              ))}
            </div>
            <p className="catalogue-control-context">
              Possible duplicates share a normalized title. Review their
              authors, editions and provenance before deciding whether they
              describe the same work.
            </p>
            <p>
              Unmatched library books:{" "}
              {report.data.counts.unmatched === null
                ? "Not assessed"
                : report.data.counts.unmatched.toLocaleString()}
              . {report.data.library_matching.message}
            </p>
          </section>
          <section aria-label={labels[queue]} aria-busy={report.isFetching}>
            <h2>{labels[queue]}</h2>
            <p ref={summary} tabIndex={-1} role="status">
              {report.data.total.toLocaleString()} records · Page{" "}
              {report.data.page} of {report.data.pages}
            </p>
            {report.data.works.length === 0 ? (
              <p>No records in this queue for the selected snapshot.</p>
            ) : (
              <ul className="catalogue-attention-works">
                {report.data.works.map((work) => (
                  <li key={work.id}>
                    <button onClick={() => browse(work.id)}>
                      {work.title || "Title not recorded"}
                    </button>
                    <ul>
                      {work.reasons.map((reason, index) => (
                        <li key={index}>{reason.replaceAll("_", " ")}</li>
                      ))}
                    </ul>
                  </li>
                ))}
              </ul>
            )}
            <nav
              className="catalogue-control-pages"
              aria-label="Attention queue pages"
            >
              <button
                disabled={route.ccp <= 1 || report.isFetching}
                onClick={() => {
                  focusResults.current = true;
                  navigate(
                    { ccp: route.ccp - 1, cv: version, ch: sha256 },
                    true,
                  );
                }}
              >
                Previous
              </button>
              <button
                disabled={route.ccp >= report.data.pages || report.isFetching}
                onClick={() => {
                  focusResults.current = true;
                  navigate(
                    { ccp: route.ccp + 1, cv: version, ch: sha256 },
                    true,
                  );
                }}
              >
                Next
              </button>
            </nav>
          </section>
          <details>
            <summary>Assessment scope</summary>
            <p>{report.data.scope}</p>
          </details>
        </>
      )}
      {report.isPending && report.fetchStatus === "fetching" && (
        <p role="status">Checking catalogue records…</p>
      )}
    </section>
  );
}
