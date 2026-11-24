import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { BookCover, type Cover } from "./BookCover";
import {
  CoverWork,
  Plates,
  RecordedFields,
  Seal,
  SourceNote,
  Week,
  healthSentence,
  type Telemetry,
  type Plate,
} from "./CatalogueGlance";
import "./catalogue-health.css";
import { sourceLabel } from "./catalogue-sources";

type Missing = { state: "unavailable"; reason: string };
type Maybe<T> = (T & { state: "observed" }) | Missing;
type Pin = { version: string; sha256: string; fixture: boolean };
type Named = { name: string; count: number };

export type HealthReport = {
  checked_at: string;
  telemetry?: Telemetry | Missing;
  status_page_url?: string;
  lately?: Maybe<{ count: number; plates: Plate[] }>;
  upscaled_examples?: Plate[];
  saved_headline?: { level: string; reasons: string[] };
  headline: {
    level: "healthy" | "attention" | "stalled" | "stale" | "unavailable";
    reasons: string[];
  };
  harvester: Maybe<{
    live: Missing;
    last_recorded_at: string | null;
    last_recorded_age_seconds: number | null;
    window: { since: string | null; since_version: string | null };
    sources: {
      source: string;
      asked: number;
      new_records: number;
      errors: number;
      last_at: string;
      last_status: string;
    }[];
    tripped: Missing;
    budget_deferred: Missing;
  }>;
  changes: Maybe<{
    from_version: string;
    to_version: string;
    added_count: number;
    removed_count: number;
    merged_count: number;
    retitled_count: number;
    added: {
      id: string;
      title: string;
      type: string | null;
      cover: Cover | null;
    }[];
    removed: { id: string; title: string; type: string | null }[];
    retitled: { id: string; from: string; to: string }[];
  }>;
  size: Maybe<{
    works: number;
    editions: number;
    authors: number;
    series: number;
    by_type: Named[];
    by_format: Named[];
    with_isbn: number;
    with_synopsis: number;
  }>;
  cycles: Missing;
  covers: Maybe<{
    saved: number;
    works_with_covers: number;
    awaiting: Missing;
    failed: Missing;
    last_download: Missing;
    upscale: Maybe<{
      upscaled: number;
      awaiting: number;
      retry: number;
      running: number;
      failed: number;
      paused: Missing;
    }>;
  }>;
  controls: Missing;
  librarium: {
    snapshot: Maybe<{
      pinned: Pin;
      dated: string;
      age_days: number;
      latest_available: string;
      behind: boolean;
      stale: boolean;
      stale_after_days: number;
      kept: string[];
    }>;
    last_sync: Maybe<{
      outcome: string;
      completed_at: string | null;
      version: string;
    }>;
    jobs: Maybe<{
      queued: number;
      running: number;
      expired_leases: number;
      oldest_queued_age_seconds: number | null;
      sample_incomplete: boolean;
      failed_last_day: number;
      latest_failure: { kind: string; at: string } | null;
    }>;
  };
  clients: { id: string; name: string; state: "unavailable"; reason: string }[];
};

type Read = { data?: HealthReport; pending: boolean; failed: boolean };

const LEVEL = {
  healthy: "Sound",
  stale: "Last heard",
  attention: "Needs attention",
  stalled: "Stalled",
  unavailable: "Unavailable",
} as const;
const SYNC = {
  succeeded: "Completed",
  failed: "Failed",
  prepared: "Prepared",
  preparing: "Preparing",
} as Record<string, string>;
const n = (value: number) => value.toLocaleString();

export function ago(seconds: number | null): string {
  if (seconds === null) return "time not recorded";
  const units: [number, string][] = [
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ];
  for (const [size, unit] of units) {
    if (seconds >= size) {
      const count = Math.floor(seconds / size);
      return `${count} ${unit}${count === 1 ? "" : "s"} ago`;
    }
  }
  return "under a minute ago";
}

function When({ value }: { value: string | null }) {
  if (!value) return <>Not recorded</>;
  const date = new Date(value);
  return (
    <time dateTime={value}>
      {Number.isNaN(date.getTime())
        ? value
        : date.toLocaleString(undefined, { hour12: true })}
    </time>
  );
}

function Unavailable({ value }: { value: Missing }) {
  return (
    <span className="health-missing">
      <span className="health-missing-label">Unavailable.</span> {value.reason}
    </span>
  );
}

function Figure({
  label,
  value,
  source,
}: {
  label: string;
  value: number | Missing | string;
  source?: string;
}) {
  return (
    <div className="health-figure">
      <dt>{label}</dt>
      <dd>
        {typeof value === "number" ? (
          <span className="health-numeral">{n(value)}</span>
        ) : typeof value === "string" ? (
          value
        ) : (
          <Unavailable value={value} />
        )}
        {source && <small className="health-figure-source">{source}</small>}
      </dd>
    </div>
  );
}

function Section({
  number,
  id,
  title,
  read,
  children,
}: {
  number: string;
  id: string;
  title: string;
  read: Read;
  children: (data: HealthReport) => React.ReactNode;
}) {
  return (
    <section
      className="health-section"
      aria-labelledby={`health-${id}`}
      aria-busy={read.pending}
    >
      <h2 id={`health-${id}`}>
        <span className="health-folio" aria-hidden="true">
          {number}
        </span>
        {title}
      </h2>
      {read.data ? (
        children(read.data)
      ) : read.failed ? (
        <p className="health-missing">
          Not read: the health report could not be loaded.
        </p>
      ) : (
        <p role="status">Reading…</p>
      )}
    </section>
  );
}

function Harvester({
  data,
  telemetry,
}: {
  data: HealthReport["harvester"];
  telemetry?: Telemetry | Missing;
}) {
  if (data.state !== "observed")
    return (
      <p>
        <Unavailable value={data} />
      </p>
    );
  const live =
    telemetry && telemetry.state !== "unavailable"
      ? telemetry.status.live
      : null;
  const latest =
    telemetry && telemetry.state !== "unavailable"
      ? telemetry.status.cycles[0]
      : null;
  const windowText = data.window.since_version
    ? `Recorded since snapshot ${data.window.since_version}`
    : "Everything this snapshot recorded";
  return (
    <>
      <dl className="health-figures">
        <Figure
          label="Live state and stalled flag"
          value={
            live
              ? `${live.state}${live.stalled ? " · stalled" : ""}${live.paused ? " · paused" : ""}`
              : data.live
          }
        />
        <div className="health-figure">
          <dt>Last recorded activity</dt>
          <dd>
            {data.last_recorded_at ? (
              <>
                {ago(data.last_recorded_age_seconds)} ·{" "}
                <When value={data.last_recorded_at} />
              </>
            ) : (
              "No harvest activity is recorded in this snapshot."
            )}
          </dd>
        </div>
      </dl>
      <h3>{windowText}</h3>
      {!data.window.since_version && (
        <p className="health-context">
          No earlier snapshot is kept, so these counts span all recorded
          history. Their errors do not change the headline.
        </p>
      )}
      {data.sources.length === 0 ? (
        <p>No harvest requests are recorded in this window.</p>
      ) : (
        <div
          className="health-table"
          role="region"
          aria-label={windowText}
          tabIndex={0}
        >
          <table>
            <thead>
              <tr>
                <th scope="col">Source</th>
                <th scope="col">Asked</th>
                <th scope="col">New records</th>
                <th scope="col">Errors</th>
                <th scope="col">Last request</th>
              </tr>
            </thead>
            <tbody>
              {data.sources.map((source) => (
                <tr key={source.source}>
                  <th scope="row">{sourceLabel(source.source)}</th>
                  <td data-label="Asked">{n(source.asked)}</td>
                  <td data-label="New records">{n(source.new_records)}</td>
                  <td
                    data-label="Errors"
                    className={source.errors ? "health-attention" : undefined}
                  >
                    {n(source.errors)}
                  </td>
                  <td data-label="Last request">
                    <span>
                      {source.last_status === "error" ? "Error" : "OK"} ·{" "}
                      <When value={source.last_at} />
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
      <dl className="health-figures">
        <Figure
          label="Tripped sources"
          value={latest ? (latest.tripped?.length ?? 0) : data.tripped}
        />
        <div className="health-figure">
          <dt>Budget deferrals</dt>
          <dd>
            {latest ? (
              <RecordedFields value={latest.budget_deferred} />
            ) : (
              <Unavailable value={data.budget_deferred} />
            )}
          </dd>
        </div>
        {latest && (
          <div className="health-figure">
            <dt>Budgets spent</dt>
            <dd>
              <RecordedFields value={latest.budget_spent} />
            </dd>
          </div>
        )}
      </dl>
    </>
  );
}

function Changes({
  data,
  openWork,
}: {
  data: HealthReport["changes"];
  openWork: (id: string) => void;
}) {
  if (data.state !== "observed")
    return (
      <p>
        <Unavailable value={data} />
      </p>
    );
  const none =
    data.added_count +
      data.removed_count +
      data.merged_count +
      data.retitled_count ===
    0;
  return (
    <>
      <p className="health-context">
        Snapshot {data.to_version} compared with {data.from_version}.
      </p>
      <dl className="health-figures">
        <Figure label="Works added" value={data.added_count} />
        <Figure label="Removed" value={data.removed_count} />
        <Figure label="Merged" value={data.merged_count} />
        <Figure label="Retitled" value={data.retitled_count} />
      </dl>
      {none && <p>No works were added, removed, merged or retitled.</p>}
      {data.added.length > 0 && (
        <>
          <h3>
            Added
            {data.added_count > data.added.length &&
              ` (first ${data.added.length} of ${n(data.added_count)})`}
          </h3>
          <ul className="health-plates">
            {data.added.map((work) => (
              <li key={work.id}>
                <button onClick={() => openWork(work.id)}>
                  <BookCover
                    cover={work.cover}
                    fallback={
                      <span className="health-title-page" aria-hidden="true">
                        {work.title}
                      </span>
                    }
                  />
                  <span className="health-plate-title">{work.title}</span>
                  {work.type && (
                    <span className="health-plate-type">
                      {work.type.replaceAll("_", " ")}
                    </span>
                  )}
                </button>
              </li>
            ))}
          </ul>
        </>
      )}
      {data.removed.length > 0 && (
        <>
          <h3>Removed</h3>
          <ul className="health-list">
            {data.removed.map((work) => (
              <li key={work.id}>{work.title}</li>
            ))}
          </ul>
        </>
      )}
      {data.retitled.length > 0 && (
        <>
          <h3>Retitled</h3>
          <ul className="health-list">
            {data.retitled.map((work) => (
              <li key={work.id}>
                <button
                  className="health-link"
                  onClick={() => openWork(work.id)}
                >
                  {work.to}
                </button>{" "}
                <span className="health-context">was {work.from}</span>
              </li>
            ))}
          </ul>
        </>
      )}
    </>
  );
}

function Breakdown({ label, rows }: { label: string; rows: Named[] }) {
  return (
    <div>
      <h3>{label}</h3>
      {rows.length === 0 ? (
        <p>None recorded.</p>
      ) : (
        <dl className="health-breakdown">
          {rows.map((row) => (
            <React.Fragment key={row.name}>
              <dt>{row.name.replaceAll("_", " ")}</dt>
              <dd className="health-numeral">{n(row.count)}</dd>
            </React.Fragment>
          ))}
        </dl>
      )}
    </div>
  );
}

function Size({ data }: { data: HealthReport["size"] }) {
  if (data.state !== "observed")
    return (
      <p>
        <Unavailable value={data} />
      </p>
    );
  return (
    <>
      <dl className="health-figures">
        <Figure label="Works" value={data.works} />
        <Figure label="Editions" value={data.editions} />
        <Figure label="Authors" value={data.authors} />
        <Figure label="Series" value={data.series} />
        <Figure label="Works with an ISBN" value={data.with_isbn} />
        <Figure label="Works with a synopsis" value={data.with_synopsis} />
      </dl>
      <div className="health-columns">
        <Breakdown label="Works by type" rows={data.by_type} />
        <Breakdown label="Editions by format" rows={data.by_format} />
      </div>
    </>
  );
}

function Covers({
  data,
  telemetry,
}: {
  data: HealthReport["covers"];
  telemetry?: Telemetry | Missing;
}) {
  const live =
    telemetry && telemetry.state !== "unavailable" ? telemetry.covers : null;
  if (data.state !== "observed" && !live)
    return (
      <p>
        <Unavailable value={data} />
      </p>
    );
  const snapshot = data.state === "observed" ? data : null;
  const unavailable = data.state === "unavailable" ? data : missingCoverField;
  const upscale =
    snapshot?.upscale.state === "observed" ? snapshot.upscale : null;
  const liveSource =
    telemetry?.state === "stale"
      ? `Last report · ${ago(telemetry.age_seconds)}`
      : "Live report";
  const figure = (
    label: string,
    current: number | string | undefined,
    recorded: number | Missing = unavailable,
  ) => (
    <Figure
      label={label}
      value={current ?? recorded}
      source={
        current !== undefined
          ? liveSource
          : typeof recorded === "number"
            ? "Served snapshot"
            : undefined
      }
    />
  );
  return (
    <>
      <dl className="health-figures">
        {figure("Saved originals", undefined, snapshot?.saved)}
        {figure("Works with covers", undefined, snapshot?.works_with_covers)}
        {figure("Awaiting download", live?.queued_images, snapshot?.awaiting)}
        {figure("Failed uploads", live?.failed_uploads, snapshot?.failed)}
        {live && "last_download_at" in live ? (
          <div className="health-figure">
            <dt>Last download</dt>
            <dd>
              <When value={live.last_download_at as string | null} />
              <small className="health-figure-source">{liveSource}</small>
            </dd>
          </div>
        ) : (
          <Figure
            label="Last download"
            value={snapshot?.last_download ?? unavailable}
          />
        )}
      </dl>
      <h3>Upscale queue</h3>
      <dl className="health-figures">
        {figure("Upscaled", live?.upscale.completed, upscale?.upscaled)}
        {figure("Awaiting", live?.upscale.queued, upscale?.awaiting)}
        {figure("Running", undefined, upscale?.running)}
        {figure("Waiting to retry", undefined, upscale?.retry)}
        {figure("Failed", live?.upscale.failed, upscale?.failed)}
        {figure(
          "Paused",
          live?.upscale.paused === undefined
            ? undefined
            : live.upscale.paused
              ? "Yes"
              : "No",
          upscale?.paused ??
            (snapshot?.upscale.state === "unavailable"
              ? snapshot.upscale
              : unavailable),
        )}
      </dl>
    </>
  );
}

const missingCoverField: Missing = {
  state: "unavailable",
  reason: "Not reported.",
};

function Librarium({ data }: { data: HealthReport["librarium"] }) {
  const { snapshot, last_sync: sync, jobs } = data;
  return (
    <>
      {snapshot.state !== "observed" ? (
        <p>
          <Unavailable value={snapshot} />
        </p>
      ) : (
        <>
          {snapshot.stale && (
            <p className="health-alert" role="alert">
              Stale: the served snapshot is {n(snapshot.age_days)} days old.
              Snapshots older than {snapshot.stale_after_days} days need
              attention.
            </p>
          )}
          {snapshot.behind && (
            <p className="health-alert" role="alert">
              Behind: snapshot {snapshot.latest_available} is saved, but
              Librarium still serves {snapshot.pinned.version}. Browsing,
              reviews and matching use the older one until the current pointer
              moves.
            </p>
          )}
          <dl className="health-figures">
            <Figure
              label="Serving"
              value={`${snapshot.pinned.version}${snapshot.pinned.fixture ? " · Fictional test data" : ""}`}
            />
            <Figure label="Newest saved" value={snapshot.latest_available} />
            <Figure
              label="Snapshot age"
              value={`${n(snapshot.age_days)} day${snapshot.age_days === 1 ? "" : "s"} (dated ${snapshot.dated})`}
            />
          </dl>
          <div>
            <h3>Snapshots kept ({snapshot.kept.length})</h3>
            <ol className="health-list">
              {snapshot.kept.map((version) => (
                <li key={version}>
                  {version}
                  {version === snapshot.pinned.version && " · serving"}
                </li>
              ))}
            </ol>
          </div>
        </>
      )}
      <h3>Last sync</h3>
      {sync.state !== "observed" ? (
        <p>
          <Unavailable value={sync} />
        </p>
      ) : (
        <p>
          {SYNC[sync.outcome] ?? sync.outcome} ·{" "}
          <When value={sync.completed_at} />
          {sync.version ? ` · ${sync.version}` : " · Not published"}
        </p>
      )}
      <h3>Librarium's jobs</h3>
      {jobs.state !== "observed" ? (
        <p>
          <Unavailable value={jobs} />
        </p>
      ) : (
        <>
          <dl className="health-figures">
            <Figure label="Queued" value={jobs.queued} />
            <Figure label="Running" value={jobs.running} />
            <Figure label="Past their lease" value={jobs.expired_leases} />
            <Figure
              label="Failed in the last day"
              value={jobs.failed_last_day}
            />
          </dl>
          <p className="health-context">
            {jobs.oldest_queued_age_seconds !== null &&
              `Oldest queued job waited ${ago(jobs.oldest_queued_age_seconds).replace(" ago", "")}. `}
            {jobs.latest_failure ? (
              <>
                Latest failure: {jobs.latest_failure.kind.replaceAll("_", " ")}{" "}
                · <When value={jobs.latest_failure.at} />.
              </>
            ) : (
              "No job failed in the last day."
            )}
            {jobs.sample_incomplete &&
              " More active jobs exist than the sample reads."}
          </p>
        </>
      )}
    </>
  );
}

export function CatalogueHealth({
  openWork,
  openOperations,
}: {
  openWork: (id: string, pin: Pin) => void;
  openOperations?: () => void;
}) {
  const report = useQuery({
    queryKey: ["catalogue-health"],
    queryFn: ({ signal }) => api<HealthReport>("catalogue/health", { signal }),
    refetchInterval: 60_000,
    retry: false,
  });
  const read: Read = {
    data: report.data,
    pending: report.isPending,
    failed: report.isError && !report.data,
  };
  const pinned =
    report.data?.librarium.snapshot.state === "observed"
      ? report.data.librarium.snapshot.pinned
      : null;
  const headline = report.data?.headline;
  return (
    <section
      className="catalogue-health"
      aria-labelledby="catalogue-health-title"
    >
      <header className="health-heading">
        <div>
          <h1 id="catalogue-health-title">Catalogue</h1>
          <p>Tool health</p>
        </div>
        <button
          aria-busy={report.isFetching}
          onClick={() => void report.refetch()}
        >
          {report.isFetching ? "Reading…" : "Refresh"}
        </button>
      </header>
      <div className="health-glance">
        <div
          className="health-headline"
          data-level={
            headline?.level ?? (report.isError ? "unavailable" : "loading")
          }
          role="status"
          aria-live="polite"
        >
          <Seal level={headline?.level ?? "unavailable"} />
          <div>
            <p className="health-level">
              {headline
                ? LEVEL[headline.level]
                : report.isError
                  ? "Unavailable"
                  : "Reading…"}
            </p>
            <p className="health-sentence">
              {report.data
                ? healthSentence(report.data.telemetry)
                : report.isError
                  ? "The health report could not be read."
                  : "Reading the latest saved report."}
            </p>
            {headline &&
              ["attention", "stalled"].includes(headline.level) &&
              headline.reasons
                .filter(
                  (reason) =>
                    reason !==
                    "Some sources need attention; the latest cycle ran with a tripped source.",
                )
                .map((reason) => (
                  <p className="health-rubric" key={reason}>
                    {reason}
                  </p>
                ))}
          </div>
        </div>
        <SourceNote
          telemetry={report.data?.telemetry}
          url={report.data?.status_page_url}
        />
      </div>
      {report.isError && (
        <div className="error" role="alert">
          <p>
            The health report could not be read: {report.error.message}
            {report.data ? ". Showing the last report." : "."}
          </p>
          <button onClick={() => void report.refetch()}>
            Retry health report
          </button>
        </div>
      )}
      <Week
        telemetry={report.data?.telemetry}
        checkedAt={report.data?.checked_at ?? new Date().toISOString()}
      />
      <section className="health-lately" aria-labelledby="health-lately-title">
        <h2 id="health-lately-title">
          <span className="health-folio" aria-hidden="true">
            II
          </span>
          Lately added
        </h2>
        {report.data?.lately?.state === "observed" ? (
          <>
            <p className="health-context">
              {report.data.lately.count.toLocaleString()} works in the latest
              snapshot
            </p>
            {report.data.lately.plates.length > 0 ? (
              <Plates
                plates={report.data.lately.plates}
                openWork={(id) => pinned && openWork(id, pinned)}
              />
            ) : (
              <p>No verified covers are available for these added works.</p>
            )}
          </>
        ) : (
          <p className="health-context">
            Added works are unavailable until they can be verified against the
            served snapshot.
          </p>
        )}
      </section>
      <CoverWork
        telemetry={report.data?.telemetry}
        examples={report.data?.upscaled_examples ?? []}
        openWork={(id) => pinned && openWork(id, pinned)}
      />
      <details className="health-details health-all-details">
        <summary>Details</summary>
        <p className="health-context">
          Report read <When value={report.data?.checked_at ?? null} />. Stored
          BL Catalog telemetry and Librarium’s saved evidence follow.
        </p>
        {report.data?.saved_headline && (
          <ul className="health-list">
            {report.data.saved_headline.reasons.map((reason) => (
              <li key={reason}>{reason}</li>
            ))}
          </ul>
        )}
        <section className="health-section" aria-label="BL Catalog status">
          <h2>BL Catalog status</h2>
          <RecordedFields value={report.data?.telemetry} />
          {report.data?.status_page_url && (
            <p>
              <a
                href={report.data.status_page_url}
                target="_blank"
                rel="noopener noreferrer"
              >
                BL Catalog status &amp; controls
              </a>
            </p>
          )}
        </section>
        <Section number="I" id="harvester" title="Harvester" read={read}>
          {(data) => (
            <Harvester data={data.harvester} telemetry={data.telemetry} />
          )}
        </Section>
        <Section
          number="II"
          id="changes"
          title="New in this snapshot"
          read={read}
        >
          {(data) => (
            <Changes
              data={data.changes}
              openWork={(id) => pinned && openWork(id, pinned)}
            />
          )}
        </Section>
        <Section number="III" id="size" title="Catalogue size" read={read}>
          {(data) => <Size data={data.size} />}
        </Section>
        <Section number="IV" id="cycles" title="Cycle history" read={read}>
          {(data) =>
            data.telemetry && data.telemetry.state !== "unavailable" ? (
              <RecordedFields value={data.telemetry.status.cycles} />
            ) : (
              <p>
                <Unavailable value={data.telemetry ?? data.cycles} />
              </p>
            )
          }
        </Section>
        <Section number="V" id="covers" title="Covers" read={read}>
          {(data) => <Covers data={data.covers} telemetry={data.telemetry} />}
        </Section>
        <Section number="VI" id="controls" title="Controls" read={read}>
          {(data) => (
            <>
              <p>
                <Unavailable value={data.controls} />
              </p>
              {openOperations && (
                <p>
                  Attention queues and reference import status stay in{" "}
                  <button className="health-link" onClick={openOperations}>
                    the operations view
                  </button>
                  .
                </p>
              )}
            </>
          )}
        </Section>
        <Section number="VII" id="librarium" title="Librarium" read={read}>
          {(data) => <Librarium data={data.librarium} />}
        </Section>
        <Section number="VIII" id="clients" title="Clients" read={read}>
          {(data) => (
            <dl className="health-clients">
              {data.clients.map((client) => (
                <div key={client.id}>
                  <dt>{client.name}</dt>
                  <dd>{client.reason}</dd>
                </div>
              ))}
            </dl>
          )}
        </Section>
      </details>
    </section>
  );
}
