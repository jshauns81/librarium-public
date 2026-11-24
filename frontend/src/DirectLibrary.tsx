import React, { useEffect, useRef, useState } from "react";
import { createPortal } from "react-dom";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { trackReturnIntent } from "./return-intent";
import type { Job } from "./types";
import type { RecordedOrigin } from "./book-workspace";
import { api, ApiError, LIBRARY_TIMEOUT } from "./api";
import { BrowseView, useBrowseView } from "./BrowseView";
import { coverRoom, loadPlace, type CoverRoom } from "./reading";
import sealUrl from "./assets/librarium-seal.png";
import "./book-room.css";
import { checkedSound, sameFile } from "./seal";
import { SeriesStrip } from "./SeriesStrip";
import { readerHref } from "./reader/address";
import "./direct-library.css";

export type DirectLibraryInventory = {
  token: string;
  observed_at: string;
  scope: string;
  library_uuid?: string;
};
export type DirectLibraryBook = {
  id: string;
  uuid?: string | null;
  title: string;
  authors: string[];
  series: string | null;
  series_index: number | null;
  publisher: string | null;
  published_at: string | null;
  languages: string[];
  identifiers: { type: string; value: string }[];
  formats: {
    format: string;
    name: string;
    size_bytes: number | null;
    recorded_size_bytes?: number | null;
    available: boolean;
  }[];
  cover: {
    url: string;
    media_type: string;
    width: number;
    height: number;
  } | null;
  description?: string | null;
};
export type DirectLibraryRoute = {
  lq: string;
  lp: number;
  lt: string;
  lw: string;
  ld: string;
  lwp?: number;
};
type Listing = {
  inventory: DirectLibraryInventory;
  total: number;
  page: number;
  pages: number;
  page_size: number;
  books: DirectLibraryBook[];
};
function Cover({
  book,
  prominent = false,
}: {
  book: DirectLibraryBook;
  prominent?: boolean;
}) {
  const [failed, setFailed] = useState("");
  const cover = book.cover;
  if (
    !cover ||
    failed === cover.url ||
    !cover.url.startsWith(
      `/api/direct-library/books/${encodeURIComponent(book.id)}/cover?`,
    ) ||
    cover.url.includes("\\")
  )
    return null;
  return (
    <img
      className="direct-cover"
      src={cover.url}
      width={cover.width}
      height={cover.height}
      alt=""
      loading={prominent ? "eager" : "lazy"}
      decoding="async"
      onError={() => setFailed(cover.url)}
    />
  );
}
function ReadActions({
  book,
  inventory,
}: {
  book: DirectLibraryBook;
  inventory: DirectLibraryInventory;
}) {
  const epub = book.formats.find(
    (file) => file.format === "EPUB" && file.available,
  );
  if (!epub) return null;
  const place = loadPlace(book.id, book.uuid);
  const query = new URLSearchParams({ inventory: inventory.token });
  query.set("format", "EPUB");
  return (
    <div className="direct-read">
      <a
        className="direct-read-primary"
        href={readerHref(book.id, inventory.token)}
      >
        {place && place.percent > 0 && place.percent < 100
          ? `Continue reading · ${place.percent}%`
          : "Read"}
      </a>
      <a
        className="direct-read-secondary"
        href={`/api/direct-library/books/${encodeURIComponent(book.id)}/file?${query}`}
        download={epub.name}
      >
        Download EPUB
      </a>
      {place?.chapter && place.percent > 0 && place.percent < 100 && (
        <p className="direct-read-place">You were at {place.chapter}.</p>
      )}
    </div>
  );
}

/** Light the room from the open book's cover; the room tokens read these from the root. */
function useCoverRoom(url: string | undefined) {
  const [room, setRoom] = useState<CoverRoom | null>(null);
  useEffect(() => {
    setRoom(null);
    if (!url) return;
    let current = true;
    coverRoom(url).then((value) => {
      if (current) setRoom(value);
    });
    return () => {
      current = false;
    };
  }, [url]);
  useEffect(() => {
    if (!room) return;
    const root = document.documentElement.style;
    root.setProperty("--mood-deep", room.deep);
    root.setProperty("--mood-light", room.light);
    return () => {
      root.removeProperty("--mood-deep");
      root.removeProperty("--mood-light");
    };
  }, [room]);
  return room;
}

const ORDINALS = [
  "first",
  "second",
  "third",
  "fourth",
  "fifth",
  "sixth",
  "seventh",
  "eighth",
  "ninth",
  "tenth",
  "eleventh",
  "twelfth",
];

function ordinal(index: number) {
  return Number.isInteger(index) && index >= 1 && index <= ORDINALS.length
    ? `the ${ORDINALS[index - 1]} book`
    : `book ${index}`;
}

function placeLine(book: DirectLibraryBook) {
  const place = loadPlace(book.id, book.uuid);
  if (place && place.percent >= 100) return "Read to the end.";
  if (place && place.percent > 0)
    return place.chapter
      ? `You left it at ${place.chapter}, ${place.percent}% in.`
      : `You left it ${place.percent}% in.`;
  return "On your shelf, not yet begun.";
}

function marginPlace(book: DirectLibraryBook) {
  const place = loadPlace(book.id, book.uuid);
  if (place && place.percent > 0 && place.percent < 100)
    return `Open${place.chapter ? ` at ${place.chapter}` : ""}. Read picks up where you stopped.`;
  if (place && place.percent >= 100) return "You have read it to the end.";
  return "Not begun on this device.";
}

function year(value: string | null) {
  const match = value?.match(/^(\d{4})/);
  return match ? match[1] : null;
}

function Facts({ book }: { book: DirectLibraryBook }) {
  const epub = book.formats.find((file) => file.format === "EPUB");
  const facts = [
    year(book.published_at) && `First published ${year(book.published_at)}`,
    book.publisher,
    epub?.size_bytes != null &&
      `EPUB, ${(epub.size_bytes / 1048576).toFixed(1)} MB`,
  ].filter(Boolean) as string[];
  if (!facts.length) return null;
  return (
    <p className="facts">
      {facts.map((fact) => (
        <span key={fact}>{fact}</span>
      ))}
    </p>
  );
}

function Blurb({ text }: { text: string }) {
  const trimmed = text.trim();
  if (!trimmed) return null;
  const first = trimmed[0];
  // Only a letter earns the initial; quotes and numerals stay in the text.
  if (!/\p{L}/u.test(first)) return <p className="blurb">{trimmed}</p>;
  return (
    <p className="blurb">
      <span className="init" aria-hidden="true">
        {first}
      </span>
      <span className="sr">{first}</span>
      {trimmed.slice(1)}
    </p>
  );
}

function recordLine(book: DirectLibraryBook) {
  const blank = [
    !book.publisher && "the publisher",
    !book.published_at && "the publication date",
  ].filter(Boolean) as string[];
  if (!blank.length) return "Publisher and date are recorded.";
  return `${blank.join(" and ")[0].toUpperCase()}${blank.join(" and ").slice(1)} ${blank.length > 1 ? "are" : "is"} blank. The reference comparison under Details shows what the catalogue has.`;
}

/** The wax seal: shown only when the latest inspection of this exact file passed. */
function FileSeal({
  book,
  inventory,
}: {
  book: DirectLibraryBook;
  inventory: DirectLibraryInventory;
}) {
  const query = useQuery({
    queryKey: [
      "library-book-seal",
      inventory.library_uuid,
      book.id,
      inventory.token,
    ],
    enabled: !!inventory.library_uuid,
    queryFn: ({ signal }) =>
      api<{ sources: { job: Job; inventory_matches: boolean }[] }>(
        `direct-library/books/${encodeURIComponent(book.id)}/workspaces?${new URLSearchParams({ library_uuid: inventory.library_uuid!, inventory: inventory.token, page: "1" })}`,
        { signal },
      ),
    retry: false,
    // A queued or running check settles into the seal (or not) by itself.
    refetchInterval: (state) =>
      state.state.data?.sources.some(
        (row) =>
          row.job.kind === "epub" &&
          ["queued", "running"].includes(row.job.state),
      )
        ? 1500
        : false,
  });
  const latest = query.data?.sources
    ?.filter((row) => row.inventory_matches && row.job.kind === "epub")
    .sort((a, b) => b.job.updated_at.localeCompare(a.job.updated_at))[0];
  const current = book.formats.find((file) => file.format === "EPUB");
  const changed =
    !!latest &&
    latest.job.state === "succeeded" &&
    !sameFile(latest.job, current?.size_bytes);
  const sound = !changed && checkedSound(latest?.job);
  if (!latest)
    return (
      <p className="say">
        Not checked yet. An inspection reads a preserved copy; the original
        stays as it is.
      </p>
    );
  const when = new Date(latest.job.updated_at).toLocaleDateString(undefined, {
    day: "numeric",
    month: "long",
  });
  const short = new Date(latest.job.updated_at).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });
  if (["queued", "running"].includes(latest.job.state))
    return <p className="say">Being checked now.</p>;
  if (changed)
    return (
      <p className="say">
        The file has changed since its last check on {when}. Check it again
        under Details.
      </p>
    );
  if (!sound)
    return (
      <p className="say">
        Last inspection, {when}:{" "}
        {latest.job.state === "succeeded"
          ? "it found something to look at."
          : `it ${latest.job.state}.`}{" "}
        Open it under Details.
      </p>
    );
  return (
    <div className="sealed">
      <div
        className="seal"
        role="img"
        aria-label={`Sealed by Librarium: checked ${when}, sound`}
      >
        <span className="strip" aria-hidden="true">
          <i>Structure</i>
          <i>checked</i>
          <b>Sound</b>
          <small>{short}</small>
        </span>
        <img src={sealUrl} alt="" />
      </div>
      <div>
        <p className="say">Its structure check passed.</p>
        <p>Checked {when}. Nothing to fix.</p>
      </div>
    </div>
  );
}

function size(bytes: number | null) {
  if (bytes === null) return "Size unavailable";
  return `${bytes.toLocaleString()} bytes`;
}
function descriptionText(value: string) {
  const template = document.createElement("template");
  template.innerHTML = value;
  template.content
    .querySelectorAll("script,style")
    .forEach((element) => element.remove());
  template.content
    .querySelectorAll("br")
    .forEach((element) => element.replaceWith("\n"));
  template.content
    .querySelectorAll("p,div,li")
    .forEach((element) => element.append("\n"));
  return template.content.textContent ?? "";
}

type ReferencePin = { version: string; sha256: string; fixture: boolean };
type NativeMatch = {
  inventory: DirectLibraryInventory;
  book: { id: string; title: string; authors: string[] };
  catalogue: ReferencePin;
  status: "matched" | "ambiguous" | "disagreement" | "unmatched";
  basis: string;
  identifiers: {
    type: string;
    value: string;
    status: string;
    canonical_isbn13?: string | null;
    editions?: {
      edition_id: string;
      work_id: string;
      format: string | null;
      disputed: boolean;
    }[];
  }[];
  candidates: {
    work_id: string;
    title: string;
    authors: { id: string; name: string }[];
    title_status: string;
    authors_status: string;
    identifier_match: boolean;
  }[];
  scope: string;
};
function ReferenceComparison({
  book,
  inventory,
  openReference,
  restoredPin,
  onReady,
}: {
  book: DirectLibraryBook;
  inventory: DirectLibraryInventory;
  openReference?: (workId: string, pin: ReferencePin) => void;
  restoredPin?: ReferencePin;
  onReady?: (unavailable?: boolean) => void;
}) {
  const [enabled, setEnabled] = useState(!!restoredPin);
  const [pin, setPin] = useState<ReferencePin | null>(restoredPin ?? null);
  const discovery = useQuery({
    queryKey: ["native-match-catalogue"],
    enabled: enabled && !pin,
    queryFn: ({ signal }) =>
      api<({ status: "ready" } & ReferencePin) | { status: "not_configured" }>(
        "catalogue",
        { signal },
      ),
    retry: false,
  });
  useEffect(() => {
    if (enabled && !pin && discovery.data?.status === "ready")
      setPin(discovery.data);
  }, [enabled, pin, discovery.data]);
  const match = useQuery({
    queryKey: [
      "direct-library",
      "match",
      book.id,
      inventory.token,
      pin?.version,
      pin?.sha256,
    ],
    enabled: !!pin,
    queryFn: async ({ signal }) => {
      const result = await api<NativeMatch>(
        `direct-library/books/${encodeURIComponent(book.id)}/match?${new URLSearchParams({ inventory: inventory.token, version: pin!.version, sha256: pin!.sha256 })}`,
        { signal },
      );
      if (
        result.book.id !== book.id ||
        result.inventory.token !== inventory.token ||
        result.catalogue.version !== pin!.version ||
        result.catalogue.sha256 !== pin!.sha256
      )
        throw new Error(
          "Reference comparison no longer identifies this book and snapshot.",
        );
      return result;
    },
    retry: false,
  });
  const error = discovery.error || match.error;
  useEffect(() => {
    if (match.data || error) onReady?.(!!error);
  }, [match.data, error]);
  const labels = {
    matched: "Reference match",
    ambiguous: "Several possible matches",
    disagreement: "Reference disagreement",
    unmatched: "No supported reference match",
  };
  return (
    <section className="direct-reference" aria-label="Reference comparison">
      <h3>Reference comparison</h3>
      {!enabled && (
        <>
          <p>
            Compare the recorded library metadata and identifiers with the
            reference catalogue.
          </p>
          <button onClick={() => setEnabled(true)}>
            Compare with reference
          </button>
        </>
      )}
      {enabled && (discovery.isFetching || match.isFetching) && (
        <p role="status">Comparing recorded library evidence…</p>
      )}
      {enabled && discovery.data?.status === "not_configured" && (
        <p>
          No reference catalogue is configured. File inspection remains
          available where enabled.
        </p>
      )}
      {error && (
        <div className="error" role="alert">
          <p>Reference comparison could not be read: {error.message}</p>
          <button
            onClick={() => {
              void discovery.refetch();
              if (pin) void match.refetch();
            }}
          >
            Retry comparison
          </button>
          {match.error instanceof ApiError && match.error.status === 409 && (
            <p>
              Refresh the library if its metadata changed. Select the current
              reference snapshot explicitly from Catalogue control if that
              snapshot changed.
            </p>
          )}
        </div>
      )}
      {match.data && !match.isError && (
        <>
          <p className="direct-match-status">{labels[match.data.status]}</p>
          <p>
            {match.data.basis.replaceAll("_", " ")}. Snapshot{" "}
            {match.data.catalogue.version}.
          </p>
          <ul className="direct-reference-candidates">
            {match.data.candidates.map((candidate) => (
              <li key={candidate.work_id}>
                <strong>{candidate.title}</strong>
                <span>
                  {candidate.authors.map((author) => author.name).join(", ") ||
                    "Author not recorded"}
                </span>
                <span>
                  Title: {candidate.title_status}. Authors:{" "}
                  {candidate.authors_status}. Identifier evidence:{" "}
                  {candidate.identifier_match
                    ? "present"
                    : "not recorded for this candidate"}
                  .
                </span>
                {openReference && (
                  <button
                    id={`library-reference-${candidate.work_id}`}
                    onClick={() =>
                      openReference(candidate.work_id, match.data!.catalogue)
                    }
                  >
                    Open reference record
                  </button>
                )}
              </li>
            ))}
          </ul>
          <p>
            This compares recorded metadata. A matching ISBN does not establish
            that the library file is the same edition or that its content is
            complete.
          </p>
          <details>
            <summary>Identifier evidence and assessment scope</summary>
            <ul>
              {match.data.identifiers.map((identifier, index) => (
                <li key={index}>
                  {identifier.type}: {identifier.value} · {identifier.status}
                  {identifier.editions?.length ? (
                    <ul>
                      {identifier.editions.map((edition, index) => (
                        <li key={index}>
                          Recorded edition {edition.edition_id}:{" "}
                          {edition.format || "Format not recorded"}
                          {edition.disputed ? " · Disputed" : ""}
                        </li>
                      ))}
                    </ul>
                  ) : null}
                </li>
              ))}
            </ul>
            <p>{match.data.scope}</p>
          </details>
        </>
      )}
    </section>
  );
}

export function DirectLibrary({
  route,
  navigate,
  inspectBook,
  openReference,
  resumeBook,
  restore: restored,
}: {
  route: DirectLibraryRoute;
  navigate: (next: Partial<DirectLibraryRoute>, push?: boolean) => void;
  inspectBook?: (
    book: DirectLibraryBook,
    inventory: DirectLibraryInventory,
  ) => void | Promise<void>;
  openReference?: (workId: string, pin: ReferencePin) => void;
  resumeBook?: (source: string) => void;
  restore?: {
    route: DirectLibraryRoute;
    scroll: number;
    focusId?: string;
    reference?: ReferencePin;
  };
}) {
  const [draft, setDraft] = useState(route.lq);
  const [generation, setGeneration] = useState(0);
  const [inspection, setInspection] = useState<{
    book: string;
    pending: boolean;
    error?: string;
  } | null>(null);
  const inspectionBusy = useRef(false);
  const [searchHost, setSearchHost] = useState<Element | null>(null);
  const presentation = useBrowseView();
  const heading = useRef<HTMLHeadingElement>(null);
  const summary = useRef<HTMLParagraphElement>(null);
  const restore = useRef<{ id: string; scroll?: number } | null>(null);
  const externalReturn = useRef<{
    saved: typeof restored;
    intent: ReturnType<typeof trackReturnIntent>;
  } | null>(null);
  useEffect(() => {
    if (!restored) return;
    const intent = trackReturnIntent(() => {
      externalReturn.current = null;
    });
    externalReturn.current = { saved: restored, intent };
    return () => intent.dispose();
  }, [restored]);
  const focusRequest = useRef<{
    kind: "detail" | "summary" | "return";
    intent: ReturnType<typeof trackReturnIntent>;
  } | null>(null);
  function requestFocus(kind: "detail" | "summary" | "return") {
    focusRequest.current?.intent.dispose();
    if (kind === "summary") restore.current = null;
    const intent = trackReturnIntent(
      () => {
        focusRequest.current = null;
        if (kind === "return") restore.current = null;
      },
      { includeCurrentFocus: true },
    );
    focusRequest.current = { kind, intent };
  }
  useEffect(() => () => focusRequest.current?.intent.dispose(), []);
  const client = useQueryClient();
  useEffect(
    () => setSearchHost(document.getElementById("workspace-search-slot")),
    [],
  );
  useEffect(() => setDraft(route.lq), [route.lq]);
  const list = useQuery<Listing>({
    queryKey: [
      "direct-library",
      "list",
      route.lq,
      route.lp,
      route.lt,
      generation,
    ],
    placeholderData: (previous, query) =>
      previous &&
      previous.inventory.token === route.lt &&
      query?.queryKey[2] === route.lq &&
      query.queryKey[3] === route.lp &&
      query.queryKey[5] === generation
        ? previous
        : undefined,
    queryFn: async ({ signal }) => {
      const params = new URLSearchParams({
        q: route.lq,
        page: String(route.lp),
      });
      if (route.lt) params.set("inventory", route.lt);
      const result = await api<Listing>(`direct-library?${params}`, {
        signal,
        timeout: LIBRARY_TIMEOUT,
      });
      if (route.lt && result.inventory.token !== route.lt)
        throw new ApiError(
          "Library metadata changed. Refresh the library to continue.",
          409,
          "direct_library_changed",
        );
      return result;
    },
    retry: false,
  });
  useEffect(() => {
    if (!route.lt && list.data && !list.isError)
      navigate({ lt: list.data.inventory.token });
  }, [route.lt, list.data, list.isError]);
  const pin = route.lt || list.data?.inventory.token || "";
  const detail = useQuery({
    queryKey: ["direct-library", "book", route.lw, pin],
    enabled: !!route.lw && !!pin,
    queryFn: async ({ signal }) => {
      const result = await api<{
        inventory: DirectLibraryInventory;
        book: DirectLibraryBook;
      }>(
        `direct-library/books/${encodeURIComponent(route.lw)}?${new URLSearchParams({ inventory: pin })}`,
        { signal, timeout: LIBRARY_TIMEOUT },
      );
      if (result.inventory.token !== pin || result.book.id !== route.lw)
        throw new ApiError(
          "Library metadata changed. Refresh the library to continue.",
          409,
          "direct_library_changed",
        );
      return result;
    },
    retry: false,
  });
  const error = list.error || detail.error;
  const changed =
    error instanceof ApiError && error.code === "direct_library_changed";
  const selected = !error ? detail.data?.book : undefined;
  const books = !list.isError ? list.data?.books : undefined;
  const room = useCoverRoom(route.lw ? selected?.cover?.url : undefined);
  const mood = room?.deep ?? null;
  function restoreExternal(unavailable = false) {
    const target = externalReturn.current;
    if (!selected || !target?.intent.isCurrent()) return;
    const control = document.getElementById(target.saved?.focusId ?? "");
    if (target.saved?.focusId && !control && !unavailable) return;
    target.intent.dispose();
    externalReturn.current = null;
    (control ?? heading.current)?.focus({ preventScroll: true });
    window.scrollTo(0, target.saved?.scroll ?? 0);
  }
  useEffect(() => {
    restoreExternal(!!error);
  }, [selected, error]);
  useEffect(() => {
    const pending = focusRequest.current;
    if (selected && pending?.kind === "detail" && pending.intent.isCurrent()) {
      pending.intent.dispose();
      focusRequest.current = null;
      heading.current?.focus({ preventScroll: true });
    }
  }, [selected]);
  useEffect(() => {
    if (!route.lw && restore.current && focusRequest.current?.kind !== "return")
      requestFocus("return");
  }, [route.lw]);
  useEffect(() => {
    if (list.isFetching) return;
    const pending = focusRequest.current;
    if (!pending?.intent.isCurrent()) return;
    if (pending.kind === "summary" && list.data) {
      pending.intent.dispose();
      focusRequest.current = null;
      summary.current?.focus();
    }
    if (pending.kind === "return" && !route.lw && restore.current && books) {
      pending.intent.dispose();
      focusRequest.current = null;
      const saved = restore.current;
      const target =
        document.getElementById(`direct-book-${saved.id}`) ?? summary.current;
      target?.focus({ preventScroll: saved.scroll !== undefined });
      if (saved.scroll !== undefined) window.scrollTo(0, saved.scroll);
      restore.current = null;
    }
  }, [route.lw, books, list.isFetching]);
  function refresh() {
    void client.cancelQueries({ queryKey: ["direct-library"] });
    client.removeQueries({ queryKey: ["direct-library", "book"] });
    setGeneration((value) => value + 1);
    requestFocus("summary");
    navigate({ lp: 1, lt: "", lw: "", ld: "", lwp: 1 });
  }
  function choose(book: DirectLibraryBook) {
    restore.current = { id: book.id, scroll: window.scrollY };
    requestFocus("detail");
    navigate({ lw: book.id, lt: pin, ld: "1", lwp: 1 }, true);
  }
  const search = (
    <form
      role="search"
      className="direct-search"
      onSubmit={(event) => {
        event.preventDefault();
        requestFocus("summary");
        navigate({ lq: draft, lp: 1, lw: "", ld: "" }, true);
      }}
    >
      <label htmlFor="direct-search">Search library</label>
      <div>
        <input
          id="direct-search"
          type="search"
          maxLength={200}
          value={draft}
          onChange={(event) => setDraft(event.target.value)}
          placeholder="Title or author"
        />
        <button type="submit">Search</button>
      </div>
    </form>
  );
  return (
    <section
      className={`direct-library ${route.lw ? "has-selection" : ""}`}
      aria-label="Direct library"
    >
      <header className="direct-heading">
        <div>
          <h1>Library</h1>
          <p className="direct-context">Reading Calibre directly · Read-only</p>
        </div>
        <button onClick={refresh}>Refresh library</button>
      </header>
      {searchHost ? createPortal(search, searchHost) : search}
      {error && (
        <div className="error" role="alert">
          <p>
            {changed
              ? "Library metadata changed. Refresh to read the current inventory."
              : `Library could not be read: ${error.message}`}
          </p>
          {!changed && (
            <button
              onClick={() => {
                void list.refetch();
                if (route.lw) void detail.refetch();
              }}
            >
              Retry library
            </button>
          )}
        </div>
      )}
      <div
        className="direct-workspace"
        data-book-open={route.lw ? "" : undefined}
      >
        <section
          className="direct-results"
          aria-label="Library books"
          aria-busy={list.isFetching}
        >
          <div className="direct-tools">
            <p
              ref={summary}
              tabIndex={-1}
              className="direct-summary"
              role="status"
            >
              {list.isPending
                ? "Reading library…"
                : list.data && !list.isError
                  ? `${list.data.total.toLocaleString()} ${list.data.total === 1 ? "book" : "books"}${route.lq ? ` for “${route.lq}”` : ""} · Page ${list.data.page} of ${list.data.pages}`
                  : "Library unavailable"}
            </p>
            <BrowseView {...presentation} />
          </div>
          {books?.length === 0 && list.data && (
            <div className="direct-empty">
              {route.lp > 1 || list.data.total > 0 ? (
                <>
                  <h2>No books on this page</h2>
                  <p>
                    {route.lp > 1
                      ? "Return to the first page to continue browsing."
                      : "Refresh the library to read this page again."}
                  </p>
                  {route.lp > 1 && (
                    <button
                      disabled={list.isFetching}
                      onClick={() => {
                        requestFocus("summary");
                        navigate({ lp: 1, lw: "", ld: "" }, true);
                      }}
                    >
                      First page
                    </button>
                  )}
                </>
              ) : route.lq ? (
                <>
                  <h2>No books match this search</h2>
                  <p>Try another title or author, or clear the search.</p>
                </>
              ) : (
                <>
                  <h2>No books in this library</h2>
                  <p>The current library read returned no books.</p>
                </>
              )}
              {route.lq && (
                <button
                  disabled={list.isFetching}
                  onClick={() => {
                    setDraft("");
                    requestFocus("summary");
                    navigate({ lq: "", lp: 1, lw: "", ld: "" }, true);
                  }}
                >
                  Clear search
                </button>
              )}
            </div>
          )}
          <ul className={`direct-books is-${presentation.view}`}>
            {books?.map((book) => (
              <li key={book.id}>
                <button
                  id={`direct-book-${book.id}`}
                  className="direct-book"
                  aria-pressed={route.lw === book.id}
                  onClick={() => choose(book)}
                >
                  <Cover book={book} />
                  <span className="direct-book-copy">
                    <span className="direct-title">{book.title}</span>
                    <span>
                      {book.authors.join(", ") || "Author not recorded"}
                    </span>
                    {book.series && (
                      <span className="direct-series">
                        {book.series}
                        {book.series_index !== null
                          ? ` · ${book.series_index}`
                          : ""}
                      </span>
                    )}
                    <span className="direct-formats">
                      {book.formats.map((file) => file.format).join(", ") ||
                        "No files recorded"}
                    </span>
                  </span>
                </button>
              </li>
            ))}
          </ul>
          {list.data && !list.isError && (
            <nav className="direct-pagination" aria-label="Library pages">
              <button
                disabled={route.lp <= 1 || list.isFetching}
                onClick={() => {
                  requestFocus("summary");
                  navigate({ lp: route.lp - 1, lw: "", ld: "" }, true);
                }}
              >
                Previous
              </button>
              <button
                disabled={route.lp >= list.data.pages || list.isFetching}
                onClick={() => {
                  requestFocus("summary");
                  navigate({ lp: route.lp + 1, lw: "", ld: "" }, true);
                }}
              >
                Next
              </button>
            </nav>
          )}
        </section>
        {route.lw && (
          <section
            className="direct-detail book-room"
            aria-label="Selected library book"
            aria-busy={detail.isFetching}
            data-mood={mood ? "" : undefined}
          >
            <div className="room">
              {room?.haze && <img className="haze" src={room.haze} alt="" />}
              <nav className="crumbs" aria-label="Breadcrumb">
                <button
                  className="back"
                  onClick={() => {
                    if (restore.current?.id !== route.lw)
                      restore.current = { id: route.lw };
                    requestFocus("return");
                    navigate({ lw: "", ld: "" }, true);
                  }}
                >
                  Back to library
                </button>
                {selected?.series && (
                  <span>
                    <span aria-hidden="true"> · </span>
                    {selected.series}
                  </span>
                )}
              </nav>
              {detail.isPending && !error && (
                <p role="status">Reading book details…</p>
              )}
              {selected && (
                <div className="desk">
                  <figure className="plate">
                    <Cover book={selected} prominent />
                    {selected.series && selected.series_index !== null && (
                      <figcaption>
                        {selected.series}, {ordinal(selected.series_index)}
                      </figcaption>
                    )}
                  </figure>
                  <div className="desk-text">
                    <p className="when">{placeLine(selected)}</p>
                    <h2 ref={heading} tabIndex={-1}>
                      {selected.title}
                    </h2>
                    <p className="by">
                      {selected.authors.join(", ") || "Author not recorded"}
                    </p>
                    {selected.series && (
                      <p className="series">
                        {selected.series}
                        {selected.series_index !== null
                          ? ` · Book ${selected.series_index}`
                          : ""}
                      </p>
                    )}
                    <Facts book={selected} />
                    {selected.description && (
                      <Blurb text={descriptionText(selected.description)} />
                    )}
                    <ReadActions
                      book={selected}
                      inventory={detail.data!.inventory}
                    />
                  </div>
                  <aside className="margin" aria-label="From the margins">
                    <div>
                      <h3>Your place</h3>
                      <p>{marginPlace(selected)}</p>
                    </div>
                    <div>
                      <h3>The catalogue knows</h3>
                      <p>
                        Its editions and identifiers, under Details. Compare
                        your record with it below.
                      </p>
                    </div>
                  </aside>
                </div>
              )}
            </div>
            {selected && (
              <>
                <section className="band" aria-labelledby="this-copy">
                  <h3 id="this-copy" className="band-title">
                    This copy
                  </h3>
                  <p className="lede">
                    What Librarium found in the file, and what it can do.
                  </p>
                  <div className="copy">
                    <article>
                      <h4>The file</h4>
                      <FileSeal
                        book={selected}
                        inventory={detail.data!.inventory}
                      />
                      <h5>Library files</h5>
                      <ul className="direct-files">
                        {selected.formats.map((file) => (
                          <li key={`${file.format}:${file.name}`}>
                            <strong>{file.format}</strong>
                            <span>{file.name}</span>
                            <span>
                              {size(file.size_bytes)} ·{" "}
                              <span>
                                {file.available ? "Available" : "Unavailable"}
                              </span>
                            </span>
                          </li>
                        ))}
                      </ul>
                      {selected.formats.length === 0 && (
                        <p>No files are recorded for this book.</p>
                      )}
                    </article>
                    <article>
                      <h4>Your Calibre record</h4>
                      <p className="say">{recordLine(selected)}</p>
                    </article>
                    <article>
                      <h4>Where it sits</h4>
                      <p className="say">
                        {selected.series
                          ? selected.series_index !== null
                            ? `Book ${selected.series_index} of ${selected.series}.`
                            : `Part of ${selected.series}.`
                          : "Not part of a recorded series."}
                      </p>
                    </article>
                  </div>
                </section>
                <hr className="rule" />
                <SeriesStrip
                  book={selected}
                  inventory={detail.data!.inventory}
                  openBook={(id) => {
                    navigate({ lw: id, ld: "1" }, true);
                    window.scrollTo(0, 0);
                  }}
                />
                <hr className="rule" />
                <section
                  className="band details"
                  aria-labelledby="book-details"
                >
                  <h3 id="book-details" className="band-title">
                    Details
                  </h3>
                  <p className="lede">
                    Everything else Librarium knows about this book, for when
                    you want it.
                  </p>
                  {resumeBook && (
                    <PreservedWork
                      key={`preserved:${selected.id}:${detail.data!.inventory.token}`}
                      book={selected}
                      inventory={detail.data!.inventory}
                      resume={resumeBook}
                      page={route.lwp ?? 1}
                      setPage={(page) => navigate({ lwp: page }, true)}
                      restoreFocusId={restored?.focusId}
                      onReady={restoreExternal}
                    />
                  )}
                  {inspectBook &&
                    selected.formats.some(
                      (file) => file.format === "EPUB" && file.available,
                    ) && (
                      <div className="direct-inspection">
                        <button
                          id="library-book-new-inspection"
                          disabled={inspection?.pending}
                          onClick={async () => {
                            if (inspectionBusy.current) return;
                            inspectionBusy.current = true;
                            const bookId = selected.id;
                            setInspection({ book: bookId, pending: true });
                            try {
                              await inspectBook(
                                selected,
                                detail.data!.inventory,
                              );
                              setInspection({ book: bookId, pending: false });
                            } catch (error) {
                              setInspection({
                                book: bookId,
                                pending: false,
                                error:
                                  error instanceof Error
                                    ? error.message
                                    : "Request failed",
                              });
                            } finally {
                              inspectionBusy.current = false;
                            }
                          }}
                        >
                          {inspection?.pending
                            ? "Preparing inspection…"
                            : inspection?.book === selected.id &&
                                inspection.error
                              ? "Retry inspection"
                              : "Start a new EPUB inspection"}
                        </button>
                        {inspection?.book === selected.id &&
                          inspection.pending && (
                            <p role="status">
                              Preserving a copy for inspection. The original
                              stays unchanged.
                            </p>
                          )}
                        {inspection?.book === selected.id &&
                          inspection.error && (
                            <p role="alert">
                              Inspection was not confirmed: {inspection.error}.
                              Retry uses the same request key.
                            </p>
                          )}
                      </div>
                    )}
                  <ReferenceComparison
                    key={`${selected.id}:${detail.data!.inventory.token}`}
                    book={selected}
                    inventory={detail.data!.inventory}
                    openReference={openReference}
                    restoredPin={restored?.reference}
                    onReady={restoreExternal}
                  />
                  <h3>Recorded metadata</h3>
                  <dl className="direct-metadata">
                    <dt>Publisher</dt>
                    <dd>{selected.publisher || "Not recorded"}</dd>
                    <dt>Published</dt>
                    <dd>{selected.published_at || "Not recorded"}</dd>
                    <dt>Languages</dt>
                    <dd>{selected.languages.join(", ") || "Not recorded"}</dd>
                    {selected.identifiers.map((identifier, index) => (
                      <React.Fragment key={`${identifier.type}:${index}`}>
                        <dt>{identifier.type}</dt>
                        <dd>{identifier.value}</dd>
                      </React.Fragment>
                    ))}
                  </dl>
                  <details>
                    <summary>Library observation</summary>
                    <p>
                      The inventory identifies the metadata read. File
                      availability is checked when read; it does not establish
                      file identity or quality.
                    </p>
                    <p>
                      Observed{" "}
                      {new Date(
                        detail.data!.inventory.observed_at,
                      ).toLocaleString()}
                    </p>
                    <p className="direct-fingerprint">
                      {detail.data!.inventory.token}
                    </p>
                  </details>
                </section>
              </>
            )}
          </section>
        )}
      </div>
    </section>
  );
}

function PreservedWork({
  book,
  inventory,
  resume,
  page,
  setPage,
  restoreFocusId,
  onReady,
}: {
  book: DirectLibraryBook;
  inventory: DirectLibraryInventory;
  resume: (id: string) => void;
  page: number;
  setPage: (page: number) => void;
  restoreFocusId?: string;
  onReady: (unavailable?: boolean) => void;
}) {
  const [featuredSelection, setFeaturedSelection] = useState<{
    page: number;
    id: string;
  } | null>(null);
  const query = useQuery({
    queryKey: [
      "library-book-workspaces",
      inventory.library_uuid,
      book.id,
      inventory.token,
      page,
    ],
    enabled: !!inventory.library_uuid,
    queryFn: async ({ signal }) => {
      const data = await api<{
        sources: {
          job: Job;
          origin: RecordedOrigin;
          inventory_matches: boolean;
        }[];
        total: number;
        page: number;
        page_size: number;
        unavailable_count?: number;
      }>(
        `direct-library/books/${encodeURIComponent(book.id)}/workspaces?${new URLSearchParams({ library_uuid: inventory.library_uuid!, inventory: inventory.token, page: String(page) })}`,
        { signal },
      );
      const unavailable = Object.hasOwn(data, "unavailable_count")
        ? data.unavailable_count
        : 0;
      if (
        data.page !== page ||
        !Number.isSafeInteger(data.total) ||
        data.total < 0 ||
        !Number.isSafeInteger(data.page_size) ||
        data.page_size < 1 ||
        data.page_size > 100 ||
        typeof unavailable !== "number" ||
        !Number.isSafeInteger(unavailable) ||
        unavailable < 0 ||
        unavailable > data.page_size ||
        !Array.isArray(data.sources) ||
        data.sources.length + unavailable > data.page_size ||
        data.sources.length + unavailable > data.total ||
        data.sources.some(
          (row) =>
            row.job.kind !== "epub" ||
            row.origin.library_uuid !== inventory.library_uuid ||
            row.origin.book_id !== book.id,
        )
      )
        throw new Error(
          "Saved work does not match this library book. Refresh before resuming.",
        );
      return { ...data, unavailable_count: unavailable };
    },
    retry: false,
    refetchInterval: (q) =>
      q.state.data?.sources.some((row) =>
        ["queued", "running"].includes(row.job.state),
      )
        ? 1500
        : false,
  });
  useEffect(() => {
    if (query.data || query.error) onReady(!!query.error);
  }, [query.data, query.error]);
  const rows = query.data?.sources ?? [];
  const featured =
    rows.find(
      (row) =>
        featuredSelection?.page === page && row.job.id === featuredSelection.id,
    ) ??
    rows.find((row) => ["queued", "running"].includes(row.job.state)) ??
    rows.find((row) => row.job.state === "succeeded") ??
    rows[0];
  useEffect(() => {
    if (featured) setFeaturedSelection({ page, id: featured.job.id });
  }, [page, featured?.job.id]);
  const otherRows = rows.filter((row) => row !== featured);
  function inspectionRow(row: (typeof rows)[number], primary = false) {
    const suffix = row.job.id.slice(-8);
    const identity = rows.some(
      (other) => other.job.id !== row.job.id && other.job.id.endsWith(suffix),
    )
      ? row.job.id
      : suffix;
    const state = {
      queued: "Queued",
      running: "Inspecting",
      succeeded: "Inspection complete",
      failed: "Failed",
      cancelled: "Cancelled",
    }[row.job.state];
    return (
      <li key={row.job.id}>
        <button
          id={`resume-book-${row.job.id}`}
          title={row.job.id}
          onClick={() => resume(row.job.id)}
        >
          {primary ? "Resume preserved work" : "Open inspection"} · {identity}
        </button>
        <p>
          {state} · Updated {new Date(row.job.updated_at).toLocaleString()}
          <br />
          {row.inventory_matches
            ? "Captured from this inventory"
            : "Historical source; the library inventory has changed"}
        </p>
      </li>
    );
  }
  return (
    <section
      className="direct-preserved-work"
      aria-label="Resume preserved work"
    >
      <h3>Resume preserved work</h3>
      {!inventory.library_uuid && (
        <p>
          The library identity is unavailable. Open saved inspections from
          Reviews.
        </p>
      )}
      {inventory.library_uuid && query.isPending && (
        <p role="status">Loading preserved inspections…</p>
      )}
      {query.isError && (
        <div role="alert" className="error">
          <p>{query.error.message}</p>
          <button onClick={() => void query.refetch()}>
            Retry preserved work
          </button>
        </div>
      )}
      {!!query.data?.unavailable_count && (
        <p role="status">
          {query.data.unavailable_count} recorded{" "}
          {query.data.unavailable_count === 1 ? "inspection" : "inspections"} on
          this page could not be verified and cannot be resumed.
        </p>
      )}
      {query.data?.total === 0 && (
        <p>
          No preserved inspection is recorded for this book. A new inspection
          keeps the original unchanged.
        </p>
      )}
      {query.data &&
        query.data.total > 0 &&
        query.data.sources.length === 0 && (
          <p>
            No verified preserved inspection is available on this page. Recorded
            work remains historical.
          </p>
        )}
      {featured && <ul>{inspectionRow(featured, true)}</ul>}
      {(otherRows.length > 0 ||
        (query.data && query.data.total > query.data.page_size)) && (
        <details
          open={
            page > 1 ||
            otherRows.some(
              (row) => restoreFocusId === `resume-book-${row.job.id}`,
            )
          }
        >
          <summary>
            Other preserved inspections · {otherRows.length} on this page
          </summary>
          <ul>{otherRows.map((row) => inspectionRow(row))}</ul>
          {query.data && query.data.total > query.data.page_size && (
            <div className="actions">
              <button disabled={page <= 1} onClick={() => setPage(page - 1)}>
                Previous preserved inspections
              </button>
              <span>Page {page}</span>
              <button
                disabled={page * query.data.page_size >= query.data.total}
                onClick={() => setPage(page + 1)}
              >
                Next preserved inspections
              </button>
            </div>
          )}
        </details>
      )}
    </section>
  );
}
