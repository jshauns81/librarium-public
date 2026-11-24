import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import {
  decodeCatalogueAuthors,
  type AuthorEvidence,
} from "./author-groups-api";
import { AliasMatches, AuthorGroups } from "./AuthorGroups";
import { ArchivistMark } from "./Identity";
import { CatalogueSupport } from "./CatalogueSupport";
import {
  useLibraryEvidence,
  LibraryEvidenceContext,
  LibraryMatchProof,
  useWorkLibraryEvidence,
  WorkLibraryEvidence,
} from "./LibraryEvidence";
import type { LibraryWork } from "./Library";
import { CatalogueReview } from "./CatalogueReview";
import { BrowseView, useBrowseView } from "./BrowseView";
import type { Cover } from "./BookCover";
import { LibraryBookArt } from "./LibraryBookArt";
import { Synopsis } from "./Synopsis";
import { trackReturnIntent, type ReturnIntent } from "./return-intent";
import { SeriesName } from "./SeriesName";
import {
  SeriesContext,
  SeriesRoom,
  kindLabel,
  catalogueArtwork,
  type SeriesCredit,
} from "./SeriesRoom";
import "./reading-room.css";
import "./catalogue-room.css";

export type CatalogueRoute = {
  cq: string;
  cp: number;
  cw: string;
  cv: string;
  ch: string;
  cs: string;
  cb: string;
  ca: string;
};
type Snapshot = { version: string; sha256: string; fixture: boolean };
type Person = {
  id: number | string;
  name: string;
  version: string;
  position?: number | null;
};
type Row = {
  id: string;
  title: string;
  authors: Person[];
  series: Person[];
  edition_count: number;
  type?: string | null;
  first_published?: string | null;
  cover?: Cover | null;
};
type Listing = {
  author_evidence?: AuthorEvidence;
  snapshot: Snapshot;
  works: Row[];
  total: number;
  page: number;
  page_size: number;
  selected_series: (Person & { credit?: SeriesCredit | null }) | null;
  selected_author: Person | null;
  position_counts?: {
    numbered: number;
    zero: number;
    unpositioned: number;
  } | null;
};
type SeriesListing = {
  snapshot: Snapshot;
  series: (Person & { work_count: number })[];
  total: number;
  page: number;
  page_size: number;
};
type Detail = Row & {
  author_evidence?: AuthorEvidence;
  snapshot: Snapshot;
  synopsis: string | null;
  ownership: string;
  editions: {
    id: string;
    format: string | null;
    isbn10: string | null;
    isbn13: string | null;
    publisher: string | null;
    release_date: string | null;
  }[];
  support: {
    field: string;
    value: string | null;
    agree: string[];
    disagree: { origin: string; value: unknown }[];
  }[];
};
type Status =
  | ({ status: "ready"; total: number } & Snapshot)
  | { status: "not_configured" };

export type CatalogueReturn = { work: string; scroll: number; context: string };

export function catalogueContextKey(route: CatalogueRoute) {
  return JSON.stringify([
    route.cv,
    route.ch,
    route.cb,
    route.cs,
    route.ca,
    route.cq,
    route.cp,
  ]);
}

export function Catalogue({
  route,
  navigate,
  returnToLibrary,
  libraryConnected = false,
  openLibrary,
  reviewsEnabled = false,
  compareSource,
}: {
  route: CatalogueRoute;
  navigate: (
    next: Partial<CatalogueRoute>,
    push?: boolean,
    state?: unknown,
  ) => void;
  returnToLibrary?: () => void;
  libraryConnected?: boolean;
  openLibrary?: (work: LibraryWork, snapshot: string) => void;
  reviewsEnabled?: boolean;
  compareSource?: (work: string, version: string, sha256: string) => void;
}) {
  const [search, setSearch] = useState(route.cq);
  const [searchHost, setSearchHost] = useState<Element | null>(null);
  useEffect(
    () => setSearchHost(document.getElementById("workspace-search-slot")),
    [],
  );
  const browseView = useBrowseView();
  const [switchError, setSwitchError] = useState("");
  const [switching, setSwitching] = useState(false);
  const queryClient = useQueryClient();
  const heading = useRef<HTMLHeadingElement>(null);
  const pageHeading = useRef<HTMLHeadingElement>(null);
  const resultSummary = useRef<HTMLParagraphElement>(null);
  const focusAfterLoad = useRef<{
    kind: "heading" | "results";
    context: string;
    from: Element | null;
  } | null>(null);
  const listContext = catalogueContextKey(route);
  const listReturn = useRef<CatalogueReturn>({
    work: "",
    scroll: 0,
    context: listContext,
  });
  const pendingListReturn = useRef<CatalogueReturn | null>(null);
  const listReturnIntent = useRef<ReturnIntent | null>(null);
  const listReturnFrame = useRef(0);
  const previousSelection = useRef({ work: route.cw, context: listContext });
  const selectedByUser = useRef(false);
  const mounted = useRef(true);
  const latestRoute = useRef(route);
  latestRoute.current = route;
  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      listReturnIntent.current?.dispose();
    };
  }, []);
  const status = useQuery({
    queryKey: ["catalogue-status"],
    queryFn: ({ signal }) => api<Status>("catalogue", { signal }),
    retry: false,
    staleTime: Infinity,
  });
  useEffect(() => {
    if (
      !route.cv &&
      !route.ch &&
      !route.cs &&
      !route.ca &&
      status.data?.status === "ready"
    )
      navigate({ cv: status.data.version, ch: status.data.sha256 });
  }, [route.cv, route.ch, route.cs, route.ca, status.data]);
  useEffect(() => setSearch(route.cq), [route.cq]);
  const params = new URLSearchParams({ version: route.cv, sha256: route.ch });
  const seriesIndex = route.cb === "series";
  const directory = useQuery({
    queryKey: ["catalogue-series", route.cv, route.ch, route.cq, route.cp],
    queryFn: ({ signal }) =>
      api<SeriesListing>(
        `catalogue/series?${new URLSearchParams({ version: route.cv, sha256: route.ch, q: route.cq, page: String(route.cp) })}`,
        { signal },
      ),
    enabled: seriesIndex && !!route.cv && !!route.ch,
    retry: false,
    staleTime: Infinity,
  });
  const listing = useQuery({
    queryKey: [
      "catalogue-list",
      route.cv,
      route.ch,
      route.cq,
      route.cp,
      route.cs,
      route.ca,
    ],
    queryFn: async ({ signal }) => {
      const value = await api<Listing>(
        `catalogue/works?${new URLSearchParams({ version: route.cv, sha256: route.ch, q: route.cq, page: String(route.cp), series: route.cs, author: route.ca })}`,
        { signal },
      );
      return decodeCatalogueAuthors(
        value,
        {
          version: route.cv,
          sha256: route.ch,
          fixture: value.snapshot?.fixture,
        },
        { page: route.cp, author: route.ca },
      );
    },
    enabled: !seriesIndex && !!route.cv && !!route.ch,
    retry: false,
    staleTime: Infinity,
  });
  const detail = useQuery({
    queryKey: ["catalogue-detail", route.cv, route.ch, route.cw],
    queryFn: async ({ signal }) => {
      const value = await api<Detail>(
        `catalogue/works/${encodeURIComponent(route.cw)}?${params}`,
        {
          signal,
        },
      );
      return decodeCatalogueAuthors(
        value,
        {
          version: route.cv,
          sha256: route.ch,
          fixture: value.snapshot?.fixture,
        },
        { work: route.cw },
      );
    },
    enabled: !seriesIndex && !!route.cw && !!route.cv && !!route.ch,
    retry: false,
    staleTime: Infinity,
  });
  useEffect(() => {
    if (route.cw && detail.data && selectedByUser.current) {
      document.querySelector(".catalogue .detail")?.scrollTo(0, 0);
      if (matchMedia("(max-width:959px), (max-height:679px)").matches)
        heading.current?.focus({ preventScroll: true });
      selectedByUser.current = false;
    }
  }, [route.cw, detail.data]);
  useEffect(() => {
    if (
      previousSelection.current.work &&
      !route.cw &&
      previousSelection.current.context === listContext
    ) {
      pendingListReturn.current =
        history.state?.catalogueReturn?.context === listContext
          ? history.state.catalogueReturn
          : listReturn.current;
      listReturnIntent.current?.dispose();
      listReturnIntent.current = trackReturnIntent(() => {
        pendingListReturn.current = null;
        cancelAnimationFrame(listReturnFrame.current);
      });
    }
    previousSelection.current = { work: route.cw, context: listContext };
    const saved = pendingListReturn.current;
    if (
      route.cw ||
      saved?.context !== listContext ||
      !listReturnIntent.current?.isCurrent()
    ) {
      pendingListReturn.current = null;
      listReturnIntent.current?.dispose();
      listReturnIntent.current = null;
      return;
    }
    listReturnFrame.current = requestAnimationFrame(() => {
      if (!listReturnIntent.current?.isCurrent()) return;
      const row = document.getElementById(`catalogue-${saved.work}`);
      if (!row) return;
      listReturnIntent.current.dispose();
      listReturnIntent.current = null;
      row.focus({ preventScroll: true });
      window.scrollTo(0, saved.scroll);
      pendingListReturn.current = null;
    });
    return () => cancelAnimationFrame(listReturnFrame.current);
  }, [route.cw, listContext, listing.data, directory.data]);
  useEffect(() => {
    const loaded = seriesIndex ? directory.data : listing.data;
    const failed = seriesIndex ? directory.error : listing.error;
    const pending = focusAfterLoad.current;
    if (!pending) return;
    if (pending.context !== listContext) {
      focusAfterLoad.current = null;
      return;
    }
    if (!loaded && !failed) return;
    const stillHere =
      document.activeElement === pending.from ||
      document.activeElement === document.body;
    const target =
      pending.kind === "heading" || failed
        ? pageHeading.current
        : resultSummary.current;
    if (stillHere) {
      target?.focus({ preventScroll: true });
      target?.scrollIntoView?.({ block: "start" });
    }
    focusAfterLoad.current = null;
  }, [
    directory.data,
    directory.error,
    listing.data,
    listing.error,
    listContext,
  ]);

  async function useCurrent() {
    const from = document.activeElement;
    setSwitching(true);
    setSwitchError("");
    try {
      const result = await status.refetch();
      if (!mounted.current || latestRoute.current !== route) return;
      if (result.error) throw result.error;
      if (result.data?.status !== "ready")
        throw new Error("No catalogue snapshot is configured");
      const next = {
        cv: result.data.version,
        ch: result.data.sha256,
        cw: "",
        cp: 1,
        cs: "",
        ca: "",
      };
      focusAfterLoad.current = {
        kind: "heading",
        context: catalogueContextKey({ ...route, ...next }),
        from,
      };
      navigate(next);
      await queryClient.invalidateQueries({ queryKey: ["catalogue-list"] });
      await queryClient.invalidateQueries({ queryKey: ["catalogue-series"] });
    } catch (error) {
      if (!mounted.current) return;
      setSwitchError(
        error instanceof Error
          ? error.message
          : "Unable to select the current snapshot",
      );
    } finally {
      if (mounted.current) setSwitching(false);
    }
  }
  function select(id: string) {
    listReturn.current = {
      work: id,
      scroll: window.scrollY,
      context: listContext,
    };
    selectedByUser.current = true;
    const fromList = !route.cw;
    if (fromList)
      history.replaceState(
        { ...history.state, catalogueReturn: listReturn.current },
        "",
      );
    navigate({ cw: id }, true, {
      catalogueReturn: listReturn.current,
      ...(fromList ? { catalogueFromList: true } : {}),
    });
    if (matchMedia("(max-width:959px), (max-height:679px)").matches)
      window.scrollTo(0, 0);
  }
  function browseSeries(id: number | string) {
    setSearch("");
    changeList(
      { cs: String(id), ca: "", cb: "works", cq: "", cp: 1, cw: "" },
      "heading",
    );
  }
  function browseMode(mode: string) {
    changeList(
      { cb: mode, cs: "", ca: "", cq: route.cq, cp: 1, cw: "" },
      "heading",
    );
  }
  function changeList(
    next: Partial<CatalogueRoute>,
    kind: "heading" | "results" = "results",
  ) {
    if (next.cw === "") previousSelection.current.work = "";
    focusAfterLoad.current = {
      kind,
      context: catalogueContextKey({ ...route, ...next }),
      from: document.activeElement,
    };
    navigate(next, true);
  }
  const source = seriesIndex
    ? directory.data?.snapshot
    : listing.data?.snapshot;
  // Keep the pinned snapshot summary steady while a new page loads.
  const shownSource = useRef<Snapshot | undefined>(undefined);
  if (source) shownSource.current = source;
  const pinned =
    shownSource.current?.version === route.cv &&
    shownSource.current?.sha256 === route.ch
      ? shownSource.current
      : undefined;
  const selectedSeries =
    !seriesIndex && route.cs ? listing.data?.selected_series : null;
  const selectedAuthor =
    !seriesIndex && route.ca ? listing.data?.selected_author : null;
  const evidenceEnabled =
    libraryConnected &&
    !seriesIndex &&
    !!selectedSeries &&
    !!source &&
    !source.fixture;
  const evidence = useLibraryEvidence(
    route.cs,
    route.cv,
    route.ch,
    evidenceEnabled,
  );
  const matchedWork = evidence.matches.get(route.cw);
  const workEvidenceEnabled =
    libraryConnected &&
    !seriesIndex &&
    !!detail.data &&
    !detail.data.snapshot.fixture &&
    !matchedWork &&
    (!evidenceEnabled || !evidence.query.isPending);
  const workEvidence = useWorkLibraryEvidence(
    route.cw,
    route.cv,
    route.ch,
    workEvidenceEnabled,
  );
  const incompletePin =
    !!route.cv !== !!route.ch ||
    ((!!route.cs || !!route.ca) && (!route.cv || !route.ch));
  const error =
    (incompletePin ? new Error("Snapshot link is incomplete") : null) ||
    (seriesIndex ? directory.error : listing.error) ||
    (!seriesIndex && detail.error) ||
    (!route.cv && status.error);
  const expired = error instanceof ApiError && error.status === 409;
  const current = status.data?.status === "ready" ? status.data : null;
  const outdated =
    !!pinned &&
    !!current &&
    (current.version !== pinned.version || current.sha256 !== pinned.sha256);
  const switchButton = (
    <button disabled={switching} onClick={useCurrent}>
      {switching ? "Selecting snapshot…" : "Use current snapshot"}
    </button>
  );
  const searchLabel = seriesIndex
    ? "Search series"
    : selectedAuthor
      ? "Search this author"
      : selectedSeries
        ? "Search this series"
        : "Search catalogue";
  const searchForm = (
    <form
      role="search"
      aria-label={searchLabel}
      className="library-search catalogue-room-search"
      onSubmit={(event) => {
        event.preventDefault();
        changeList({ cq: search.trim(), cp: 1, cw: "" });
      }}
    >
      <label className="sr-only" htmlFor="catalogue-search">
        {searchLabel}
      </label>
      <input
        id="catalogue-search"
        type="search"
        value={search}
        maxLength={200}
        onChange={(event) => setSearch(event.target.value)}
        placeholder={seriesIndex ? "Series name" : "Title, author or series"}
      />
      <button type="submit" aria-label={searchLabel}>
        <svg width="16" height="16" viewBox="0 0 16 16" aria-hidden="true">
          <circle cx="6.5" cy="6.5" r="4.5" fill="none" stroke="currentColor" />
          <path d="m10 10 4 4" stroke="currentColor" />
        </svg>
      </button>
    </form>
  );

  return (
    <section
      className={`catalogue catalogue-room reading-room browse-${browseView.view} ${!seriesIndex && route.cw ? "has-selected-work" : ""} ${selectedSeries ? "series-room" : ""}`}
      aria-label="Catalogue"
    >
      {searchHost ? createPortal(searchForm, searchHost) : searchForm}
      {returnToLibrary && (
        <button className="library-return" onClick={returnToLibrary}>
          Return to library results
        </button>
      )}
      {!seriesIndex && route.cw && (
        <button
          className="back"
          onClick={() =>
            history.state?.catalogueFromList
              ? history.back()
              : navigate({ cw: "" })
          }
        >
          {route.ca
            ? "Back to author"
            : route.cs
              ? "Back to series"
              : "Back to catalogue"}
        </button>
      )}
      <div
        className={`page-heading ${!seriesIndex && route.cw ? "is-detail" : ""}`}
      >
        <div>
          <h1 ref={pageHeading} tabIndex={-1}>
            {seriesIndex ? (
              "Series"
            ) : selectedAuthor ? (
              selectedAuthor.name
            ) : selectedSeries ? (
              <SeriesName name={selectedSeries.name} />
            ) : (
              "Catalogue"
            )}
          </h1>
          {selectedAuthor && selectedSeries && (
            <p className="catalogue-author-context">
              In <SeriesName name={selectedSeries.name} />
            </p>
          )}
          {selectedAuthor && (
            <>
              <AliasMatches
                evidence={listing.data?.author_evidence}
                authorId={String(selectedAuthor.id)}
              />
              <AuthorGroups
                evidence={listing.data?.author_evidence}
                authorId={String(selectedAuthor.id)}
              />
            </>
          )}
          {!selectedSeries && pinned && (
            <p className="catalogue-snapshot">
              Snapshot {pinned.version}
              {pinned.fixture ? " · fictional contract data" : ""}
            </p>
          )}
          {!seriesIndex && route.ca && (
            <button
              className="catalogue-all-works"
              onClick={() => changeList({ ca: "", cp: 1, cw: "" }, "heading")}
            >
              All works
            </button>
          )}
          {selectedSeries && listing.data && (
            <SeriesContext
              credit={selectedSeries.credit}
              total={listing.data.total}
              filtered={!!route.cq || !!route.ca}
              evidence={evidenceEnabled ? evidence : null}
              version={route.cv}
            />
          )}
        </div>
        {pinned && (
          <details className="snapshot-details">
            <summary>
              {pinned.fixture ? "Fixture data" : "Details"}
              {outdated && " · update available"}
            </summary>
            <dl className="provenance">
              <dt>Version</dt>
              <dd>{pinned.version}</dd>
              {detail.data && (
                <>
                  <dt>Work</dt>
                  <dd>{detail.data.id}</dd>
                </>
              )}
              <dt>Fingerprint</dt>
              <dd className="hash">{pinned.sha256}</dd>
            </dl>
            <p className="context-note">
              Fixed, read-only snapshot; IDs belong to this version. Records
              don't confirm ownership.
            </p>
            {!error && !switchError && switchButton}
          </details>
        )}
      </div>
      {switchError && (
        <div className="error" role="alert">
          {switchError}. {switchButton}
        </div>
      )}
      {error && (
        <div className="error" role="alert">
          {error.message}.{" "}
          {(expired || incompletePin) && !switchError && switchButton}
          {!expired && !incompletePin && (
            <button
              onClick={() => {
                if (route.cv) {
                  if (seriesIndex) void directory.refetch();
                  else void listing.refetch();
                  if (route.cw) void detail.refetch();
                } else void status.refetch();
              }}
            >
              Retry catalogue
            </button>
          )}
        </div>
      )}
      {!route.cv && status.isPending ? (
        <p role="status">Checking catalogue connection…</p>
      ) : !route.cv && status.data?.status === "not_configured" ? (
        <div className="empty">
          <ArchivistMark className="connection-mark" variant="small" />
          <h2>No catalogue connected</h2>
          <p>Waiting for the first published snapshot.</p>
          <button onClick={() => status.refetch()}>Check connection</button>
        </div>
      ) : (
        route.cv && (
          <>
            {evidenceEnabled && <LibraryEvidenceContext evidence={evidence} />}
            <div
              className={`${seriesIndex ? "series-directory" : "collection-layout"} ${!seriesIndex && route.cw ? "has-selection" : ""}`}
            >
              <section
                className="collection"
                aria-label="Catalogue results"
                aria-busy={
                  seriesIndex ? directory.isFetching : listing.isFetching
                }
              >
                <div className="catalogue-controls">
                  <nav
                    className="catalogue-browse"
                    aria-label="Catalogue browsing"
                  >
                    <button
                      aria-pressed={!seriesIndex && !route.cs}
                      onClick={() => browseMode("works")}
                    >
                      Works
                    </button>
                    <button
                      aria-pressed={seriesIndex || !!route.cs}
                      onClick={() => browseMode("series")}
                    >
                      Series
                    </button>
                  </nav>
                  {!seriesIndex && <BrowseView {...browseView} />}
                </div>
                {seriesIndex && directory.isPending && (
                  <p role="status">Loading catalogue series…</p>
                )}
                {seriesIndex && directory.data && (
                  <>
                    <p
                      className="list-summary"
                      role="status"
                      ref={resultSummary}
                      tabIndex={-1}
                    >
                      {directory.data.total.toLocaleString()} matching series
                    </p>
                    {directory.data.series.length === 0 ? (
                      <div className="empty">
                        <h2>
                          {directory.data.total > 0
                            ? "This page has no results"
                            : "No matching series"}
                        </h2>
                        <p>
                          {directory.data.total > 0
                            ? "Return to the first page of these results."
                            : route.cq
                              ? "Try another series name, or clear your search."
                              : "This snapshot has no recorded series."}
                        </p>
                        {directory.data.total > 0 && (
                          <button onClick={() => changeList({ cp: 1 })}>
                            First page
                          </button>
                        )}
                        {route.cq && (
                          <button
                            onClick={() => {
                              setSearch("");
                              changeList({ cq: "", cp: 1 });
                            }}
                          >
                            Clear search
                          </button>
                        )}
                      </div>
                    ) : (
                      <>
                        <ul
                          className="series-directory-list"
                          aria-label="Catalogue series"
                        >
                          {directory.data.series.map((series) => (
                            <li key={series.id}>
                              <button
                                className="series-directory-entry"
                                onClick={() => browseSeries(series.id)}
                              >
                                <span className="bibliography">
                                  <strong>
                                    <SeriesName name={series.name} />
                                  </strong>
                                </span>
                                <span className="edition-count">
                                  {series.work_count}{" "}
                                  {series.work_count === 1 ? "work" : "works"}
                                </span>
                              </button>
                            </li>
                          ))}
                        </ul>
                        <div className="pagination">
                          <button
                            disabled={route.cp <= 1}
                            onClick={() => {
                              changeList({ cp: route.cp - 1 });
                            }}
                          >
                            Previous
                          </button>
                          <span>
                            Page {route.cp} of{" "}
                            {Math.ceil(
                              directory.data.total / directory.data.page_size,
                            )}
                          </span>
                          <button
                            disabled={
                              route.cp * directory.data.page_size >=
                              directory.data.total
                            }
                            onClick={() => {
                              changeList({ cp: route.cp + 1 });
                            }}
                          >
                            Next
                          </button>
                        </div>
                      </>
                    )}
                  </>
                )}
                {!seriesIndex && listing.isPending && (
                  <p role="status">Loading catalogue works…</p>
                )}
                {!seriesIndex && listing.data && (
                  <>
                    <div className="results-toolbar">
                      <p
                        className="list-summary"
                        role="status"
                        ref={resultSummary}
                        tabIndex={-1}
                      >
                        {selectedSeries
                          ? `${listing.data.total.toLocaleString()} ${route.cq || route.ca ? "matching " : ""}${listing.data.total === 1 ? "work" : "works"} in recorded order`
                          : `${listing.data.total.toLocaleString()} matching ${listing.data.total === 1 ? "work" : "works"}`}
                        {listing.data.snapshot.fixture
                          ? " · fictional contract data"
                          : ""}
                      </p>
                    </div>
                    {!selectedAuthor && (
                      <AliasMatches evidence={listing.data.author_evidence} />
                    )}
                    {!selectedAuthor &&
                      listing.data.author_evidence?.status !== "available" && (
                        <AuthorGroups evidence={listing.data.author_evidence} />
                      )}
                    {listing.data.works.length === 0 ? (
                      <div className="empty">
                        <h2>
                          {listing.data.total > 0
                            ? "This page has no results"
                            : route.ca && !selectedAuthor
                              ? "Author not found in this snapshot"
                              : route.cs && !selectedSeries
                                ? "Series not found in this snapshot"
                                : "No matching catalogue works"}
                        </h2>
                        <p>
                          {listing.data.total > 0
                            ? "Return to the first page of these results."
                            : route.cs && !selectedSeries
                              ? "Series identifiers belong to one catalogue version. Choose a series from this snapshot."
                              : selectedSeries
                                ? "No titles match this search in the selected series."
                                : "Try a title, author or series name."}
                        </p>
                        {listing.data.total > 0 && (
                          <button onClick={() => changeList({ cp: 1 })}>
                            First page
                          </button>
                        )}
                        {route.cs && !selectedSeries && (
                          <button onClick={() => browseMode("series")}>
                            Browse all series
                          </button>
                        )}
                        {route.cq && (
                          <button
                            onClick={() => {
                              setSearch("");
                              changeList({ cq: "", cp: 1, cw: "" });
                            }}
                          >
                            Clear search
                          </button>
                        )}
                      </div>
                    ) : (
                      <SeriesRoom
                        seriesId={selectedSeries ? route.cs : undefined}
                        works={listing.data.works}
                        positionCounts={
                          selectedSeries
                            ? listing.data.position_counts
                            : undefined
                        }
                        evidence={selectedSeries ? evidence : undefined}
                        selectedId={route.cw}
                        select={select}
                        page={route.cp}
                        total={listing.data.total}
                        pageSize={listing.data.page_size}
                        changePage={(cp) => changeList({ cp })}
                      />
                    )}
                  </>
                )}
              </section>
              {!seriesIndex && (
                <aside className="detail" aria-label="Catalogue evidence">
                  {route.cw ? (
                    detail.isPending ? (
                      <p role="status">Loading catalogue evidence…</p>
                    ) : detail.error ? (
                      <div className="error" role="alert">
                        <h2>Unable to load this work</h2>
                        <p>{detail.error.message}</p>
                        {!(
                          detail.error instanceof ApiError &&
                          detail.error.status === 409
                        ) && (
                          <button onClick={() => void detail.refetch()}>
                            Retry work evidence
                          </button>
                        )}
                        <button onClick={() => navigate({ cw: "" })}>
                          {route.ca
                            ? "Return to author"
                            : route.cs
                              ? "Return to series"
                              : "Return to catalogue"}
                        </button>
                      </div>
                    ) : (
                      detail.data && (
                        <div
                          className="folio library-detail-folio"
                          key={detail.data.id}
                        >
                          <div className="work-introduction reading-book-top">
                            <LibraryBookArt
                              work={catalogueArtwork(detail.data)}
                              cover={detail.data.cover}
                              seriesId={route.cs || undefined}
                              prominent
                            />
                            <div>
                              <h2
                                ref={heading}
                                tabIndex={-1}
                                className="work-title"
                              >
                                {detail.data.title}
                              </h2>
                              {detail.data.authors.length ? (
                                <ul
                                  className="series-links"
                                  aria-label="This work's authors"
                                >
                                  {detail.data.authors.map((author) => (
                                    <li key={author.id}>
                                      <button
                                        aria-label={`Browse author ${author.name}`}
                                        onClick={() =>
                                          changeList(
                                            {
                                              ca: String(author.id),
                                              cb: "works",
                                              cq: listing.data?.author_evidence?.groups.some(
                                                (group) =>
                                                  group.author.id ===
                                                    String(author.id) &&
                                                  group.matched_alias_count > 0,
                                              )
                                                ? route.cq
                                                : "",
                                              cp: 1,
                                              cw: "",
                                            },
                                            "heading",
                                          )
                                        }
                                      >
                                        {author.name}
                                      </button>
                                    </li>
                                  ))}
                                </ul>
                              ) : (
                                <p className="author">Author not recorded</p>
                              )}
                              <p className="context-note">
                                {detail.data.type
                                  ? kindLabel(detail.data.type)
                                  : "Type not recorded"}
                                {detail.data.first_published
                                  ? ` · First published ${detail.data.first_published}`
                                  : " · Date not recorded"}
                              </p>
                              {!!detail.data.series.length && (
                                <ul
                                  className="series-links"
                                  aria-label="This work's series"
                                >
                                  {detail.data.series.map((s) => (
                                    <li key={s.id}>
                                      <button
                                        aria-label={`Browse ${s.name}`}
                                        onClick={() => browseSeries(s.id)}
                                      >
                                        <SeriesName name={s.name} />
                                        {s.position != null
                                          ? ` · ${s.position}`
                                          : " · no position"}
                                      </button>
                                    </li>
                                  ))}
                                </ul>
                              )}
                            </div>
                          </div>
                          {detail.data.synopsis && (
                            <Synopsis text={detail.data.synopsis} />
                          )}
                          <AuthorGroups
                            evidence={detail.data.author_evidence}
                          />
                          {compareSource && (
                            <div className="catalogue-source-comparison">
                              <button
                                id="catalogue-compare-source"
                                onClick={() =>
                                  compareSource(
                                    detail.data.id,
                                    route.cv,
                                    route.ch,
                                  )
                                }
                              >
                                Compare with an inspected EPUB
                              </button>
                              <p className="context-note">
                                Choose a preserved source inspection, then
                                compare against this exact catalogue work and
                                snapshot.
                              </p>
                            </div>
                          )}
                          {matchedWork && evidence.data?.snapshot ? (
                            <LibraryMatchProof
                              work={matchedWork}
                              snapshot={evidence.data.snapshot}
                              checkedAt={evidence.data.checked_at}
                              coverage={evidence.data.coverage}
                              openLibrary={openLibrary}
                              stale={!!evidence.query.error}
                              refreshing={evidence.query.isFetching}
                              refresh={() => void evidence.query.refetch()}
                            />
                          ) : workEvidenceEnabled ? (
                            <WorkLibraryEvidence
                              evidence={workEvidence}
                              openLibrary={openLibrary}
                            />
                          ) : (
                            <p className="context-note">
                              Ownership unconfirmed
                            </p>
                          )}
                          <details
                            className="detail-section"
                            open={detail.data.editions.length <= 3}
                          >
                            <summary>
                              Editions · {detail.data.edition_count}
                            </summary>
                            {detail.data.editions.length ? (
                              <>
                                <ul className="editions">
                                  {detail.data.editions.map((edition) => (
                                    <li key={edition.id}>
                                      <strong>
                                        {edition.format ||
                                          "Format not recorded"}
                                      </strong>
                                      <span>
                                        {edition.release_date ||
                                          "Date not recorded"}
                                      </span>
                                      <small>
                                        {edition.publisher ||
                                          "Publisher not recorded"}
                                      </small>
                                      <small>
                                        {edition.isbn13 ||
                                          edition.isbn10 ||
                                          "ISBN not recorded"}
                                      </small>
                                    </li>
                                  ))}
                                </ul>
                                {detail.data.edition_count >
                                  detail.data.editions.length && (
                                  <p className="context-note">
                                    First {detail.data.editions.length} shown
                                  </p>
                                )}
                              </>
                            ) : (
                              <p>None recorded</p>
                            )}
                          </details>
                          {reviewsEnabled && (
                            <CatalogueReview
                              key={`${detail.data.id}:${route.cv}:${route.ch}`}
                              workId={detail.data.id}
                              title={detail.data.title}
                              version={detail.data.snapshot.version}
                              sha256={detail.data.snapshot.sha256}
                              fixture={detail.data.snapshot.fixture}
                            />
                          )}
                          <CatalogueSupport records={detail.data.support} />
                        </div>
                      )
                    )
                  ) : (
                    <div className="detail-empty">
                      <ArchivistMark />
                      <h2>Select a work</h2>
                      <p>Editions and source support appear here.</p>
                    </div>
                  )}
                </aside>
              )}
            </div>
          </>
        )
      )}
    </section>
  );
}
