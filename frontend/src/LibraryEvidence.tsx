import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import type { LibraryWork } from "./Library";

type Evidence = {
  status:
    "ready" | "loading" | "version_mismatch" | "not_configured" | "unsupported";
  catalogue_version?: string | null;
  checked_at?: string | null;
  coverage?: "complete" | "partial" | "unknown";
  loading?: boolean;
  snapshot?: string;
  truncated?: boolean;
  works?: LibraryWork[];
};

export const libraryMatchLabel = (work: LibraryWork) => {
  const label =
    work.state === "direct"
      ? "Direct match"
      : work.state === "contained"
        ? "In a collection"
        : work.state === "pending"
          ? "Pending ID"
          : "Unconfirmed";
  return (
    label +
    (!work.current && ["direct", "contained"].includes(work.state)
      ? " · saved match"
      : "")
  );
};

const coverageLabel = (coverage?: string) =>
  coverage === "complete"
    ? "Complete check"
    : coverage === "partial"
      ? "Partial check"
      : "Coverage unknown";

function Checked({ at }: { at?: string | null }) {
  return at ? (
    <time dateTime={at}>
      {new Date(at).toLocaleString(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      })}
    </time>
  ) : (
    <>No check date</>
  );
}

export function useLibraryEvidence(
  series: string,
  version: string,
  sha256: string,
  enabled: boolean,
) {
  const query = useQuery({
    queryKey: ["library-series-evidence", series, version, sha256],
    queryFn: ({ signal }) =>
      api<Evidence>(
        `library/series?${new URLSearchParams({ series, version, sha256 })}`,
        { signal },
      ),
    enabled,
    retry: false,
    staleTime: 30000,
  });
  const data = query.data;
  const matches =
    enabled && data?.status === "ready" && data.catalogue_version === version
      ? new Map((data.works ?? []).map((work) => [work.id, work]))
      : new Map<string, LibraryWork>();
  return { query, data, matches };
}

export function useWorkLibraryEvidence(
  workId: string,
  version: string,
  sha256: string,
  enabled: boolean,
) {
  const query = useQuery({
    queryKey: ["library-work-evidence", workId, version, sha256],
    queryFn: ({ signal }) =>
      api<Evidence>(
        `library/works/${encodeURIComponent(workId)}?${new URLSearchParams({ version, sha256 })}`,
        { signal },
      ),
    enabled,
    retry: false,
    staleTime: 30000,
  });
  const data = query.data;
  const match =
    enabled && data?.status === "ready" && data.catalogue_version === version
      ? data.works?.find((work) => work.id === workId)
      : undefined;
  return { query, data, match };
}

export function WorkLibraryEvidence({
  evidence,
  openLibrary,
}: {
  evidence: ReturnType<typeof useWorkLibraryEvidence>;
  openLibrary?: (work: LibraryWork, snapshot: string) => void;
}) {
  const { query, data, match } = evidence;
  if (match && data?.snapshot)
    return (
      <LibraryMatchProof
        work={match}
        snapshot={data.snapshot}
        checkedAt={data.checked_at}
        coverage={data.coverage}
        openLibrary={openLibrary}
        stale={!!query.error}
        refreshing={query.isFetching}
        refresh={() => void query.refetch()}
      />
    );
  return (
    <section className="detail-section" aria-label="Saved match for this work">
      <h3>Library</h3>
      <p>
        {query.isPending ? (
          <span role="status">Reading saved evidence…</span>
        ) : query.error ? (
          "Library evidence unavailable"
        ) : data?.status === "version_mismatch" ? (
          "Library check uses a different catalogue version · unconfirmed"
        ) : data?.status === "loading" ? (
          "Library Finish is loading · try again shortly"
        ) : data?.status === "not_configured" ? (
          "Library not connected"
        ) : data?.status === "unsupported" ? (
          "This title can't be checked · unconfirmed"
        ) : (
          "No saved match · may still be in your library"
        )}
        {data?.truncated && " · incomplete search, unconfirmed"}
      </p>
      <button disabled={query.isFetching} onClick={() => void query.refetch()}>
        {query.isFetching ? "Checking…" : "Check library"}
      </button>
    </section>
  );
}

export function LibraryEvidenceContext({
  evidence,
}: {
  evidence: ReturnType<typeof useLibraryEvidence>;
}) {
  const { query, data, matches } = evidence;
  return (
    <section
      className="library-evidence-context"
      aria-label="Saved library evidence"
    >
      <div>
        {query.isPending ? (
          <p role="status">Reading saved library matches…</p>
        ) : query.error ? (
          <p>
            {data?.status === "ready"
              ? "Refresh failed · showing earlier matches, may be out of date"
              : "Library evidence unavailable"}
          </p>
        ) : data?.status === "not_configured" ? (
          <p>Library not connected</p>
        ) : data?.status === "version_mismatch" ? (
          <p>Library check uses a different catalogue version · unconfirmed</p>
        ) : data?.status === "loading" ? (
          <p role="status">Library Finish is loading · refresh shortly</p>
        ) : data ? (
          <>
            <p>
              {matches.size.toLocaleString()} saved{" "}
              {matches.size === 1 ? "match" : "matches"} ·{" "}
              {coverageLabel(data.coverage)} · <Checked at={data.checked_at} />
              {data.truncated && " · partial list"}
              {data.loading && " · updating"}
            </p>
            <details>
              <summary>About these matches</summary>
              <p>
                From Library Finish's saved check. Unmarked titles may still be
                in your library; some kinds and series aren't checked.
                {data.truncated &&
                  " Only part of the saved evidence was loaded."}
              </p>
            </details>
          </>
        ) : null}
      </div>
      <button disabled={query.isFetching} onClick={() => void query.refetch()}>
        {query.isFetching ? "Reading saved matches…" : "Refresh saved matches"}
      </button>
    </section>
  );
}

export function LibraryMatchProof({
  work,
  snapshot,
  checkedAt,
  coverage,
  openLibrary,
  stale = false,
  refreshing = false,
  refresh,
}: {
  work: LibraryWork;
  snapshot: string;
  checkedAt?: string | null;
  coverage?: "complete" | "partial" | "unknown";
  openLibrary?: (work: LibraryWork, snapshot: string) => void;
  stale?: boolean;
  refreshing?: boolean;
  refresh?: () => void;
}) {
  const href = `/?${new URLSearchParams({ lq: work.title, lo: "all", lt: snapshot })}`;
  return (
    <section className="detail-section" aria-label="Saved match for this work">
      <h3>Library</h3>
      <p>{libraryMatchLabel(work)}</p>
      <p className="context-note">
        {coverageLabel(coverage)} · <Checked at={checkedAt} />
        {!work.current && " · current copy unconfirmed"}
        {stale && " · refresh failed, showing saved match"}
      </p>
      {work.copies.length > 0 && (
        <>
          <h4>Calibre copies</h4>
          <ul className="library-copy-list">
            {work.copies.map((copy) => (
              <li key={copy.calibre_id}>
                {copy.title}
                <span className="context-note">
                  {" · "}
                  Calibre #{copy.calibre_id}
                  {copy.last_known && " · last known copy"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {work.contained_in.length > 0 && (
        <>
          <h4>In collections</h4>
          <ul className="library-copy-list">
            {work.contained_in.map((copy) => (
              <li key={copy.calibre_id}>
                {copy.title}
                <span className="context-note">
                  {" · "}
                  Calibre #{copy.calibre_id}
                  {copy.last_known && " · last known copy"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {work.candidates.length > 0 && (
        <>
          <h4>Incoming</h4>
          <ul className="library-copy-list">
            {work.candidates.map((candidate, index) => (
              <li key={index}>
                {candidate.title}
                <span className="context-note">
                  {" · "}
                  {candidate.stage === "inbox" ? "Inbox" : "Shelve"} ·{" "}
                  {candidate.confidence === "possible"
                    ? "possible match"
                    : "saved identification"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      <a
        className="library-evidence-link"
        href={href}
        onClick={(event) => {
          if (
            openLibrary &&
            event.button === 0 &&
            !event.metaKey &&
            !event.ctrlKey &&
            !event.shiftKey &&
            !event.altKey
          ) {
            event.preventDefault();
            openLibrary(work, snapshot);
          }
        }}
      >
        View in library
      </a>
      {refresh && (
        <button disabled={refreshing} onClick={refresh}>
          {refreshing ? "Refreshing…" : "Refresh match"}
        </button>
      )}
    </section>
  );
}
