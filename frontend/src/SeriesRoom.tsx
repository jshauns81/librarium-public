import React from "react";
import type { LibraryWork } from "./Library";
import { savedMatch, shelfCredits } from "./Library";
import { LibraryBookArt } from "./LibraryBookArt";
import { libraryMatchLabel, type useLibraryEvidence } from "./LibraryEvidence";
import type { Cover } from "./BookCover";
import { SeriesName } from "./SeriesName";

export type SeriesCredit = { names: string[]; others: number };
export type SeriesWork = {
  id: string;
  title: string;
  authors: { id: number | string; name: string }[];
  series: { id: number | string; name: string; position?: number | null }[];
  type?: string | null;
  first_published?: string | null;
  cover?: Cover | null;
  edition_count?: number;
};
type Evidence = ReturnType<typeof useLibraryEvidence>;
type PositionCounts = { numbered: number; zero: number; unpositioned: number };

export const kindLabel = (value: string) => {
  const words = value.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
};

const n = (value: number) => value.toLocaleString();

export function seriesCreditLabel(credit?: SeriesCredit | null) {
  if (!credit) return null;
  if (!credit.names.length) return credit.others > 1 ? "Various authors" : null;
  const names = credit.names.join(" and ");
  return credit.others > 0
    ? `${names} and ${n(credit.others)} ${credit.others === 1 ? "other" : "others"}`
    : names;
}

// Mirrors the Library shelf summary: saved history never reads as current,
// and a truncated overlay only supports a lower bound.
export function seriesShelfSummary({
  current,
  saved,
  total,
  truncated = false,
}: {
  current: number;
  saved: number;
  total: number;
  truncated?: boolean;
}) {
  const matched = current + saved;
  if (matched === 0)
    return truncated
      ? "no saved matches in this partial list"
      : "no saved matches in this check";
  if (truncated)
    return `at least ${n(matched)} of ${n(total)} shelved · partial list`;
  if (current && saved)
    return `${n(matched)} of ${n(total)} shelved: ${n(current)} with a matched copy and ${n(saved)} with a saved match`;
  const clause = saved ? "with a saved match" : "with a matched copy";
  return matched === total
    ? `${n(total)} shelved, ${total === 1 ? "" : "every one "}${clause}`
    : `${n(matched)} of ${n(total)} shelved ${clause}`;
}

function shelvedSummary(evidence: Evidence, version: string, total: number) {
  const data = evidence.data;
  if (!data || data.status !== "ready" || data.catalogue_version !== version)
    return null;
  let current = 0;
  let saved = 0;
  for (const work of evidence.matches.values()) {
    if (savedMatch(work)) saved += 1;
    else if (work.state === "direct" || work.state === "contained")
      current += 1;
  }
  return seriesShelfSummary({
    current,
    saved,
    total,
    truncated: !!data.truncated,
  });
}

export function SeriesContext({
  credit,
  total,
  filtered,
  evidence,
  version,
}: {
  credit?: SeriesCredit | null;
  total: number;
  filtered: boolean;
  evidence: Evidence | null;
  version: string;
}) {
  const creditLabel = seriesCreditLabel(credit);
  const summary =
    !filtered && evidence ? shelvedSummary(evidence, version, total) : null;
  const works = total === 1 ? "work" : "works";
  return (
    <p className="series-context">
      {creditLabel && (
        <>
          <span className="series-credit">{creditLabel}</span>
          <span aria-hidden="true">{" · "}</span>
        </>
      )}
      <span className="series-total">
        {filtered
          ? `${n(total)} matching ${works} in this series`
          : `${n(total)} ${works} in the catalogue`}
      </span>
      {summary && (
        <>
          <span aria-hidden="true">{" · "}</span>
          <span className="series-shelved">{summary}</span>
        </>
      )}
    </p>
  );
}

function membership(work: SeriesWork, seriesId: string) {
  return work.series.find((series) => String(series.id) === seriesId);
}

function positionGroup(work: SeriesWork, seriesId: string) {
  const position = membership(work, seriesId)?.position;
  return position == null
    ? "unpositioned"
    : position === 0
      ? "zero"
      : "numbered";
}

// The reading-room art reads a Library work; a catalogue record carries the
// same title, authors and membership without any ownership state.
export function catalogueArtwork(work: SeriesWork): LibraryWork {
  return {
    id: work.id,
    title: work.title,
    kind: work.type ?? "",
    authors: work.authors.map((author) => author.name),
    series: work.series.map((series) => ({
      id: String(series.id),
      name: series.name,
      position: series.position ?? null,
      shelf_eligible: true,
    })),
    first_published: work.first_published ?? null,
    state: "unknown",
    current: false,
    copies: [],
    contained_in: [],
    candidates: [],
  };
}

export function SeriesRoom({
  seriesId,
  works,
  positionCounts,
  evidence,
  selectedId,
  select,
  page,
  total,
  pageSize,
  changePage,
}: {
  seriesId?: string;
  works: SeriesWork[];
  positionCounts?: PositionCounts | null;
  evidence?: Evidence;
  selectedId: string;
  select: (id: string) => void;
  page: number;
  total: number;
  pageSize: number;
  changePage: (page: number) => void;
}) {
  return (
    <>
      <ol
        className="series-shelves"
        aria-label={
          seriesId ? "Works in recorded series order" : "Catalogue works"
        }
      >
        {works.map((work, index) => {
          const group = seriesId ? positionGroup(work, seriesId) : "numbered";
          const position = seriesId
            ? membership(work, seriesId)?.position
            : undefined;
          const matched = seriesId ? evidence?.matches.get(work.id) : undefined;
          const year = work.first_published?.match(/^\d{4}/)?.[0];
          return (
            <React.Fragment key={work.id}>
              {seriesId &&
                positionCounts &&
                group !== "numbered" &&
                (index === 0 ||
                  positionGroup(works[index - 1], seriesId) !== group) && (
                  <li className="series-group-item">
                    <h2 className="series-group">
                      {group === "zero" ? "Recorded at 0" : "No position"}
                      {" · "}
                      {positionCounts[group]}
                    </h2>
                  </li>
                )}
              <li>
                <button
                  className="shelf-entry series-entry"
                  id={`catalogue-${work.id}`}
                  aria-pressed={selectedId === work.id}
                  onClick={() => select(work.id)}
                >
                  <LibraryBookArt
                    work={catalogueArtwork(work)}
                    cover={work.cover}
                    seriesId={seriesId}
                  />
                  <span className="shelf-caption">
                    <strong>{work.title}</strong>
                    <span className="sr-only">.</span>{" "}
                    <span className="book-author">
                      {shelfCredits(work.authors.map((author) => author.name))}
                    </span>
                    <span className="sr-only">.</span>{" "}
                    <span className="series-context-line">
                      {seriesId && (
                        <span className="series-position">
                          {position != null && (
                            <span className="sr-only">Series position </span>
                          )}
                          {position ?? "No position"}
                        </span>
                      )}
                      {work.type && (
                        <>
                          <span className="sr-only">, </span>
                          {seriesId && <span aria-hidden="true">{" · "}</span>}
                          <span>{kindLabel(work.type)}</span>
                        </>
                      )}
                      {year && (
                        <>
                          <span className="sr-only">, </span>
                          {(seriesId || work.type) && (
                            <span aria-hidden="true">{" · "}</span>
                          )}
                          <span>{year}</span>
                        </>
                      )}
                    </span>
                    {!seriesId && work.series.length > 0 && (
                      <span className="catalogue-memberships">
                        {work.series.slice(0, 2).map((member, index) => (
                          <React.Fragment key={`${member.id}:${index}`}>
                            {index > 0 && (
                              <span aria-hidden="true">{" · "}</span>
                            )}
                            <span>
                              <SeriesName name={member.name} />
                              {member.position != null
                                ? ` · ${member.position}`
                                : ""}
                            </span>
                          </React.Fragment>
                        ))}
                        {work.series.length > 2 &&
                          ` · ${work.series.length - 2} more series`}
                      </span>
                    )}
                    {!seriesId && work.edition_count != null && (
                      <span className="edition-count">
                        {work.edition_count === 0
                          ? "No editions recorded"
                          : `${work.edition_count} ${work.edition_count === 1 ? "edition" : "editions"}`}
                      </span>
                    )}
                    <span className="sr-only">.</span>
                    {matched && (
                      <>
                        {" "}
                        <span className={`library-state ${matched.state}`}>
                          <span className="status-dot" />
                          {libraryMatchLabel(matched)}
                        </span>
                        <span className="sr-only">.</span>
                      </>
                    )}
                  </span>
                </button>
              </li>
            </React.Fragment>
          );
        })}
      </ol>
      <div className="pagination">
        <button disabled={page <= 1} onClick={() => changePage(page - 1)}>
          Previous
        </button>
        <span>
          Page {page} of {Math.max(1, Math.ceil(total / pageSize))}
        </span>
        <button
          disabled={page * pageSize >= total}
          onClick={() => changePage(page + 1)}
        >
          Next
        </button>
      </div>
    </>
  );
}
