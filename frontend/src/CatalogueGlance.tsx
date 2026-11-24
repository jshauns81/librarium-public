import React, { useState } from "react";
import { BookCover, type Cover } from "./BookCover";
import sealUrl from "./assets/librarium-seal.png";
import { sourceLabel } from "./catalogue-sources";

export type Cycle = {
  started_at: string;
  duration_s?: number;
  inbox_new_records?: number;
  harvest_new_records?: number;
  stages?: Record<string, { status: string }>;
  tripped?: string[];
  tripped_reasons?: Record<string, string>;
  budget_deferred?: Record<string, number>;
  budget_spent?: string[];
};
export type Telemetry = {
  state: "observed" | "stale";
  fetched_at: string;
  age_seconds: number;
  failure: string;
  status: {
    now?: string;
    live: {
      state: string;
      phase?: string | null;
      paused?: boolean;
      stalled?: boolean;
      next_cycle_at?: string | null;
    };
    cycles: Cycle[];
  };
  covers: {
    queued_images?: number;
    failed_uploads?: number;
    last_download_at?: string | null;
    upscale: {
      enabled?: boolean;
      paused?: boolean;
      state?: string;
      completed?: number;
      queued?: number;
      failed?: number;
    };
  };
};
export type Missing = { state: "unavailable"; reason: string };
export type Plate = {
  id: string;
  title: string;
  cover: Cover;
  collected_in?: string | null;
};

export const clock = (value: string) =>
  new Date(value).toLocaleTimeString(undefined, {
    hour: "numeric",
    minute: "2-digit",
    hour12: true,
  });

export function healthSentence(telemetry?: Telemetry | Missing): string {
  if (!telemetry || telemetry.state === "unavailable")
    return "The harvester’s live status is unavailable.";
  if (telemetry.state === "stale")
    return `Last heard at ${clock(telemetry.fetched_at)}; awaiting a fresh report.`;
  const live = telemetry.status.live;
  if (live.paused) return "The harvester is paused.";
  if (live.stalled) return "The harvester has stopped reporting progress.";
  if (live.state === "idle")
    return live.next_cycle_at
      ? `The harvester is resting; its next run is scheduled for ${clock(live.next_cycle_at)}.`
      : "The harvester is resting; its next run has not been reported.";
  const stages: Record<string, string> = {
    starting: "The harvester is starting.",
    setup: "The harvester is preparing its sources.",
    import_inbox: "The harvester is gathering incoming records.",
    harvest: "The harvester is gathering catalogue records.",
    rebuild: "The harvester is rebuilding the catalogue.",
    publish: "The harvester is publishing a snapshot.",
    stopped: "The harvester is stopped.",
    unknown: "The harvester has not reported its state.",
  };
  return (
    stages[live.phase ?? ""] ??
    stages[live.state] ??
    "The harvester is working."
  );
}

export function Seal({ level }: { level: string }) {
  const state = ["attention", "stalled"].includes(level)
    ? "broken"
    : level === "healthy"
      ? "whole"
      : "muted";
  return (
    <span className="health-seal" data-seal={state} aria-hidden="true">
      <img src={sealUrl} alt="" />
      {state === "broken" && <img src={sealUrl} alt="" />}
    </span>
  );
}

export function SourceNote({
  telemetry,
  url,
}: {
  telemetry?: Telemetry | Missing;
  url?: string;
}) {
  if (!telemetry || telemetry.state === "unavailable") return null;
  const latest = telemetry.status.cycles[0];
  if (!latest?.tripped?.length) return null;
  const groups = new Map<string, string[]>();
  for (const source of latest.tripped) {
    const reason = latest.tripped_reasons?.[source] ?? "Source unavailable";
    groups.set(reason, [...(groups.get(reason) ?? []), sourceLabel(source)]);
  }
  return (
    <aside className="health-margin" role="note" aria-label="Tripped sources">
      <p>
        {telemetry.state === "stale"
          ? "Sources at last report"
          : "Sources need attention"}
      </p>
      <ul>
        {[...groups].map(([reason, names]) => (
          <li key={reason}>
            <strong>
              {names.length === 1
                ? names[0]
                : `${names.slice(0, -1).join(", ")} and ${names.at(-1)}`}
            </strong>
            {names.length === 1 ? " is" : " are"} switched off:{" "}
            {names.length > 1
              ? reason.replace("API key rejected", "API keys rejected")
              : reason}
            .
          </li>
        ))}
      </ul>
      {url && (
        <a href={url} target="_blank" rel="noopener noreferrer">
          Open BL Catalog status &amp; controls
        </a>
      )}
    </aside>
  );
}

const dayKey = (date: Date) =>
  `${date.getFullYear()}-${date.getMonth()}-${date.getDate()}`;
const records = (cycle: Cycle) =>
  (cycle.inbox_new_records ?? 0) + (cycle.harvest_new_records ?? 0);
export const failedCycle = (cycle: Cycle) =>
  Object.values(cycle.stages ?? {}).some((s) => s.status === "error");

export function Week({
  telemetry,
  checkedAt,
}: {
  telemetry?: Telemetry | Missing;
  checkedAt: string;
}) {
  const today = new Date(checkedAt);
  const [selected, select] = useState<string | null>(null);
  const days = Array.from({ length: 7 }, (_, i) => {
    const date = new Date(today);
    date.setDate(date.getDate() - 6 + i);
    return { date, key: dayKey(date) };
  });
  const cycles =
    telemetry && telemetry.state !== "unavailable"
      ? telemetry.status.cycles
      : [];
  const active = days.find((day) => day.key === selected) ?? days[6];
  const seen = cycles.filter(
    (cycle) => dayKey(new Date(cycle.started_at)) === active.key,
  );
  const total = seen.reduce((sum, cycle) => sum + records(cycle), 0);
  const dateLabel = (date: Date) =>
    date.toLocaleDateString(undefined, {
      weekday: "long",
      month: "short",
      day: "numeric",
    });
  const note =
    !telemetry || telemetry.state === "unavailable"
      ? `Cycle history is unavailable. ${telemetry?.reason ?? "Waiting for the health report to load."}`
      : seen.length
        ? `${dateLabel(active.date)}: ${total ? `${total.toLocaleString()} new records` : "no new records"}${seen.some(failedCycle) ? "; a stage failed" : ""}${seen.some((c) => c.tripped?.length) ? "; ran with a tripped source" : ""}.`
        : `No cycle is recorded for ${dateLabel(active.date)}.`;
  return (
    <section className="health-week" aria-labelledby="health-week-title">
      <h2 id="health-week-title">
        <span className="health-folio" aria-hidden="true">
          I
        </span>
        The week
      </h2>
      <div className="health-days" role="group" aria-label="Select a day">
        {days.map((day, i) => {
          const entries = cycles.filter(
            (cycle) => dayKey(new Date(cycle.started_at)) === day.key,
          );
          return (
            <button
              key={day.key}
              aria-pressed={active.key === day.key}
              aria-label={dateLabel(day.date)}
              data-today={i === 6 || undefined}
              onClick={() => select(day.key)}
            >
              <span>
                {day.date.toLocaleDateString(undefined, { weekday: "short" })}
              </span>
              <span className="health-day-date">{day.date.getDate()}</span>
              <span className="health-marks">
                {entries.map((cycle) => (
                  <span
                    key={cycle.started_at}
                    className="health-cycle"
                    data-filled={records(cycle) > 0 || undefined}
                    data-broken={failedCycle(cycle) || undefined}
                    data-ringed={!!cycle.tripped?.length || undefined}
                    aria-label={`${clock(cycle.started_at)}: ${records(cycle) ? "new records" : "quiet"}${failedCycle(cycle) ? ", stage failed" : ""}${cycle.tripped?.length ? ", tripped source" : ""}`}
                    role="img"
                  />
                ))}
                {!entries.length && (
                  <span className="health-no-cycle" aria-hidden="true" />
                )}
              </span>
            </button>
          );
        })}
      </div>
      <p className="health-day-note" aria-live="polite">
        {note}
      </p>
      <p className="health-legend">
        Filled: new records · Hollow: quiet · Broken: stage failed · Ringed:
        tripped source
      </p>
      {telemetry?.state === "stale" && (
        <p className="health-context">Cycle marks are from the last report.</p>
      )}
    </section>
  );
}

export function Plates({
  plates,
  openWork,
  examples = false,
}: {
  plates: Plate[];
  openWork: (id: string) => void;
  examples?: boolean;
}) {
  return (
    <ul className={examples ? "health-examples" : "health-cascade"}>
      {plates.map((plate) => (
        <li key={plate.id}>
          <button onClick={() => openWork(plate.id)}>
            <BookCover
              cover={plate.cover}
              fallback={
                <span className="health-art-missing">
                  {plate.title}
                  <br />
                  Cover unavailable
                </span>
              }
            />
            <span className="health-plate-title">{plate.title}</span>
            {plate.collected_in && (
              <span className="health-collected">
                Collected in {plate.collected_in}
              </span>
            )}
          </button>
        </li>
      ))}
    </ul>
  );
}

export function CoverWork({
  telemetry,
  examples,
  openWork,
}: {
  telemetry?: Telemetry | Missing;
  examples: Plate[];
  openWork: (id: string) => void;
}) {
  const art =
    telemetry && telemetry.state !== "unavailable"
      ? telemetry.covers.upscale
      : null;
  const completed = art?.completed ?? 0,
    queued = art?.queued ?? 0,
    failed = art?.failed ?? 0;
  const total = completed + queued + failed;
  const available =
    art &&
    typeof art.completed === "number" &&
    typeof art.queued === "number" &&
    typeof art.failed === "number";
  return (
    <section
      className="health-cover-work"
      aria-labelledby="health-cover-work-title"
    >
      <div>
        <h2 id="health-cover-work-title">
          <span className="health-folio" aria-hidden="true">
            III
          </span>
          The cover work
        </h2>
        <p>
          {available
            ? `${telemetry?.state === "stale" ? "At last report, " : ""}${completed.toLocaleString()} cover upscales complete; ${queued.toLocaleString()} queued${art.paused ? "; upscaling is paused" : art.enabled === false ? "; upscaling is disabled" : art.state === "idle" ? "; the upscaler is resting" : "; the upscaler is working"}${failed ? "; some need attention" : ""}.`
            : "Cover progress is unavailable."}
        </p>
        {available && total > 0 && (
          <progress
            max={total}
            value={completed}
            aria-label="Completed cover upscale jobs"
          />
        )}
      </div>
      <div>
        {examples.length > 0 ? (
          <>
            <p className="health-context">Upscaled examples</p>
            <Plates plates={examples} openWork={openWork} examples />
          </>
        ) : (
          <p className="health-context">
            No verified upscaled examples are available.
          </p>
        )}
      </div>
    </section>
  );
}

export function RecordedFields({ value }: { value: unknown }) {
  if (value === null || value === undefined) return <span>Not reported</span>;
  if (typeof value === "boolean") return <span>{value ? "Yes" : "No"}</span>;
  if (typeof value === "number") return <span>{value.toLocaleString()}</span>;
  if (typeof value === "string") {
    const date = /^\d{4}-\d\d-\d\dT/.test(value) ? new Date(value) : null;
    return date && !Number.isNaN(date.getTime()) ? (
      <time dateTime={value}>
        {date.toLocaleString(undefined, { hour12: true })}
      </time>
    ) : (
      <span>{sourceLabel(value) || "None"}</span>
    );
  }
  if (Array.isArray(value))
    return value.length ? (
      <ol className="health-list">
        {value.map((v, i) => (
          <li key={i}>
            <RecordedFields value={v} />
          </li>
        ))}
      </ol>
    ) : (
      <span>None recorded</span>
    );
  return (
    <dl className="health-recorded">
      {Object.entries(value as Record<string, unknown>).map(([key, item]) => (
        <div key={key}>
          <dt>{sourceLabel(key).replaceAll("_", " ")}</dt>
          <dd>
            <RecordedFields value={item} />
          </dd>
        </div>
      ))}
    </dl>
  );
}
