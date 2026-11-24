import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, LIBRARY_TIMEOUT } from "./api";
import type { CataloguePin, CoverEntry } from "./cover-review-api";

const providers = [
  ["apple", "Apple Books"],
  ["google", "Google Books"],
  ["openlibrary", "Open Library"],
  ["hardcover", "Hardcover"],
  ["goodreads", "Goodreads"],
  ["lexicanum_live", "Lexicanum (live)"],
  ["lexicanum", "Lexicanum (archived copy)"],
];
type Search = {
  id: string;
  entry_id: string;
  state: string;
  candidate_count: number;
  query: { title: string; author: string; isbn: string };
  sources: {
    id: string;
    name: string;
    state: string;
    title_results?: number;
    title_mismatch?: number;
  }[];
};
const states: Record<string, string> = {
  not_needed: "Not needed: stronger matches found",
  pending: "Waiting",
  running: "Searching",
  results: "Results ready",
  empty: "No covers found. Refine the search or try another source.",
  not_configured:
    "Not configured. Ask the operator to set up an access key. Other sources remain available.",
  partial:
    "Partial coverage. The archive check did not finish; any covers found remain available. Retry to check further.",
  unavailable: "Unavailable. Try again later or choose another source.",
  rate_limited: "Rate limited. Try again in a few minutes.",
  timed_out: "Timed out. Try this source again.",
  failed: "Could not check this source. Try again.",
  cancelled: "Cancelled. Search again when ready.",
  challenged: "Challenged by the source. Try later or use another source.",
  busy: "Busy. Retry shortly.",
};
// A source whose every metadata result was dropped for its title has no choices from this
// run (nothing was fetched), and says so. Its upstream state ("empty" or "partial") is kept,
// so a partial source shows both facts. Rows without the counts keep the ordinary text.
const noTitleMatch =
  "Results found, but none matched this title. Refine the title or try another source.";
type SourceStatus = {
  state: string;
  title_results?: number;
  title_mismatch?: number;
};
const sourceText = (s: SourceStatus) =>
  ["empty", "partial"].includes(s.state) &&
  (s.title_results ?? 0) > 0 &&
  s.title_mismatch === s.title_results
    ? s.state === "partial"
      ? `${states.partial} ${noTitleMatch}`
      : noTitleMatch
    : states[s.state];
function decode(value: unknown, entry: CoverEntry): Search {
  const v = value as Search;
  if (
    !v ||
    v.entry_id !== entry.id ||
    !/^[a-f0-9-]{36}$/.test(v.id) ||
    !["queued", "running", "complete", "cancelled", "failed"].includes(
      v.state,
    ) ||
    !Number.isSafeInteger(v.candidate_count) ||
    v.candidate_count < 0 ||
    v.candidate_count > 24 ||
    !Array.isArray(v.sources) ||
    v.sources.length > 7 ||
    v.sources.some(
      (s) =>
        !s ||
        !(s.state in states) ||
        typeof s.name !== "string" ||
        s.name.length > 80 ||
        [s.title_results, s.title_mismatch].some(
          (n) =>
            n !== undefined && (!Number.isSafeInteger(n) || n < 0 || n > 6),
        ),
    ) ||
    !v.query ||
    [v.query.title, v.query.author, v.query.isbn].some(
      (s) => typeof s !== "string" || s.length > 300,
    )
  )
    throw new Error(
      "Search progress could not be verified. Retry the progress check.",
    );
  return v;
}
export function CoverSourceSearch({
  entry,
  inventory,
  pin,
  csrf,
  enabled,
  changed,
}: {
  entry: CoverEntry;
  inventory: string;
  pin: CataloguePin | null;
  csrf: string;
  enabled: boolean;
  changed: () => void;
}) {
  const client = useQueryClient();
  const [open, setOpen] = useState(false);
  const [history, setHistory] = useState<Search | null>(null);
  const [fields, setFields] = useState({
    title: entry.title || "",
    author: entry.authors.join(", "),
    isbn: entry.isbn || "",
  });
  const [sources, setSources] = useState(providers.map((p) => p[0]));
  const [image, setImage] = useState("");
  const key = ["cover-search", entry.id];
  const current = useQuery({
    queryKey: key,
    enabled: enabled && !!pin,
    retry: false,
    queryFn: async ({ signal }) => {
      const v = await api<{ search: unknown }>(
        `cover-reviews/${entry.id}/searches`,
        { signal },
      );
      return v.search === null ? null : decode(v.search, entry);
    },
    refetchInterval: (q) =>
      q.state.data && ["queued", "running"].includes(q.state.data.state)
        ? 1200
        : false,
    refetchOnWindowFocus: false,
  });
  const search = current.data;
  const progress = search
    ? history && JSON.stringify(history.query) === JSON.stringify(search.query)
      ? [...providers.map(([id]) => id), "paste"].flatMap((id) => {
          const item =
            search.sources.find((s) => s.id === id) ||
            history.sources.find((s) => s.id === id);
          return item ? [item] : [];
        })
      : search.sources
    : [];
  useEffect(() => {
    if (search)
      setHistory((old) => {
        if (!old || JSON.stringify(old.query) !== JSON.stringify(search.query))
          return search;
        const merged = [...providers.map(([id]) => id), "paste"].flatMap(
          (id) => {
            const item =
              search.sources.find((s) => s.id === id) ||
              old.sources.find((s) => s.id === id);
            return item ? [item] : [];
          },
        );
        return { ...search, sources: merged };
      });
  }, [search]);
  const active = !!search && ["queued", "running"].includes(search.state);
  const seen = useRef("");
  const edited = useRef(false);
  const restored = useRef(false);
  useEffect(() => {
    if (search && !restored.current) {
      restored.current = true;
      if (!edited.current) setFields(search.query);
    }
  }, [search]);
  useEffect(() => {
    const observation = search
      ? `${search.id}:${search.candidate_count}:${search.state}`
      : "";
    if (observation && observation !== seen.current) {
      seen.current = observation;
      changed();
    }
  }, [search, changed]);
  const start = useMutation({
    mutationFn: async ({
      imageUrl,
      sourceIds,
      query,
      refreshBrowser = false,
    }: {
      imageUrl: string;
      sourceIds: string[];
      query: Search["query"];
      refreshBrowser?: boolean;
    }) =>
      decode(
        await api<unknown>(`cover-reviews/${entry.id}/searches`, {
          method: "POST",
          headers: {
            "X-CSRFToken": csrf,
            "Idempotency-Key": crypto.randomUUID(),
          },
          body: JSON.stringify({
            revision: entry.revision,
            inventory,
            ...pin,
            query,
            sources: imageUrl ? [] : sourceIds,
            image_url: imageUrl,
            ...(refreshBrowser ? { refresh_browser: true } : {}),
          }),
          timeout: LIBRARY_TIMEOUT,
        }),
        entry,
      ),
    onSuccess: (v) => client.setQueryData(key, v),
  });
  const cancel = useMutation({
    mutationFn: async () =>
      decode(
        await api<unknown>(
          `cover-reviews/${entry.id}/searches/${search!.id}/cancel`,
          {
            method: "POST",
            headers: { "X-CSRFToken": csrf },
            body: "{}",
          },
        ),
        entry,
      ),
    onSuccess: (v) => client.setQueryData(key, v),
  });
  const error = start.error || cancel.error || current.error;
  return (
    <section className="cover-source-search" aria-label="Web cover search">
      <button
        disabled={active || start.isPending}
        onClick={() => {
          setOpen(true);
          if (enabled && pin)
            start.mutate({
              imageUrl: "",
              sourceIds: providers.map((p) => p[0]),
              query: {
                title: entry.title || "",
                author: entry.authors.join(", "),
                isbn: entry.isbn || "",
              },
            });
        }}
      >
        Search the web
      </button>
      {open &&
        (!enabled ? (
          <p role="status">
            Web cover sources are not enabled. Stored choices remain available.
          </p>
        ) : (
          <>
            <p>
              Find another edition or different artwork. Search terms do not
              change your book’s metadata.
            </p>
            <details>
              <summary>Refine search</summary>
              <div className="cover-search-fields">
                {(
                  [
                    ["title", "Search title"],
                    ["author", "Search author"],
                    ["isbn", "Search ISBN"],
                  ] as const
                ).map(([field, label]) => (
                  <label key={field}>
                    {label}
                    <input
                      value={fields[field]}
                      maxLength={field === "isbn" ? 32 : 300}
                      onChange={(e) => {
                        edited.current = true;
                        setFields({ ...fields, [field]: e.target.value });
                      }}
                    />
                  </label>
                ))}
              </div>
              <fieldset>
                <legend>Sources</legend>
                {providers.map(([id, name]) => (
                  <label key={id}>
                    <input
                      type="checkbox"
                      checked={sources.includes(id)}
                      onChange={(e) =>
                        setSources(
                          e.target.checked
                            ? [...sources, id]
                            : sources.filter((s) => s !== id),
                        )
                      }
                    />
                    {name}
                  </label>
                ))}
              </fieldset>
              <p>
                Lexicanum archived copies are checked when other matches are
                weak.
              </p>
              <button
                disabled={
                  !pin ||
                  active ||
                  start.isPending ||
                  !sources.length ||
                  (!fields.title.trim() && !fields.isbn.trim())
                }
                onClick={() =>
                  start.mutate({
                    imageUrl: "",
                    sourceIds: sources,
                    query: fields,
                  })
                }
              >
                Search again
              </button>
            </details>
            <form
              onSubmit={(e) => {
                e.preventDefault();
                start.mutate({ imageUrl: image, sourceIds: [], query: fields });
              }}
            >
              <label>
                Paste image URL
                <input
                  type="url"
                  required
                  pattern="https://.*"
                  maxLength={4096}
                  value={image}
                  placeholder="https://example.org/cover.jpg"
                  onChange={(e) => setImage(e.target.value)}
                />
              </label>
              <button disabled={!pin || active || start.isPending || !image}>
                Fetch image
              </button>
            </form>
          </>
        ))}
      {search && (
        <div role="status" aria-live="polite" aria-atomic="true">
          <p>
            {search.state === "complete" &&
            search.sources.every(
              (s) => !["pending", "running"].includes(s.state),
            )
              ? "Search finished"
              : search.state === "cancelled"
                ? "Search cancelled"
                : search.state === "failed"
                  ? "Search failed"
                  : `Searching ${search.sources.length} source${search.sources.length === 1 ? "" : "s"}…`}
          </p>
          <ul>
            {progress.map((s) => (
              <li key={s.id}>
                {providers.find((p) => p[0] === s.id)?.[1] || s.name}:{" "}
                {s.id === "hardcover" && s.state === "unavailable"
                  ? "Unavailable: access was rejected or the source could not be reached. Ask the operator to check source access."
                  : sourceText(s)}
                {[
                  "partial",
                  "rate_limited",
                  "timed_out",
                  "failed",
                  "unavailable",
                  "challenged",
                  "busy",
                ].includes(s.state) && (
                  <button
                    aria-label={`Retry ${s.name}`}
                    disabled={
                      active || start.isPending || (s.id === "paste" && !image)
                    }
                    onClick={() =>
                      start.mutate({
                        imageUrl: s.id === "paste" ? image : "",
                        sourceIds: [s.id],
                        query: search.query,
                        refreshBrowser: s.id === "goodreads",
                      })
                    }
                  >
                    Retry
                  </button>
                )}
                {s.id === "goodreads" &&
                  ["results", "empty"].includes(s.state) && (
                    <button
                      disabled={active || start.isPending}
                      onClick={() =>
                        start.mutate({
                          imageUrl: "",
                          sourceIds: [s.id],
                          query: search.query,
                          refreshBrowser: true,
                        })
                      }
                    >
                      Refresh Goodreads
                    </button>
                  )}
              </li>
            ))}
          </ul>
        </div>
      )}
      {active && (
        <button onClick={() => cancel.mutate()} disabled={cancel.isPending}>
          Cancel search
        </button>
      )}
      {error && (
        <div role="alert">
          <p>{error.message}</p>
          <button
            onClick={() => {
              start.reset();
              cancel.reset();
              void current.refetch();
            }}
          >
            Retry progress check
          </button>
        </div>
      )}
    </section>
  );
}
