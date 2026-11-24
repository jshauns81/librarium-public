import React, { useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { api, ApiError } from "./api";
import {
  decodeCensus,
  decodeEntry,
  fetchQueue,
  fetchSuggestions,
  type Suggestion,
  type CoverEntry,
  type CoverQueue,
  type ReviewState,
} from "./cover-review-api";
import "./cover-review.css";
import { CoverPicker } from "./CoverPicker";

export type CoverRoute = { crs: string; crr: string; crp: number };
type SkipIntent = { entry: CoverEntry; skipped: boolean; key: string };
const states: [ReviewState, string][] = [
  ["todo", "To do"],
  ["done", "Done"],
  ["skipped", "Skipped"],
];
function title(entry: CoverEntry) {
  return entry.title || "Untitled book";
}
function reason(entry: CoverEntry) {
  const facts = entry.facts;
  if (facts.status === "unresolved")
    return "Current cover could not be checked";
  if (facts.reasons.includes("missing")) return "No current cover";
  if (facts.reasons.includes("generated")) return "Title and author only";
  if (facts.reasons.includes("blank")) return "Blank cover";
  return facts.width && facts.height
    ? `${facts.width} × ${facts.height} px`
    : "Dimensions unavailable";
}
function CurrentArt({
  entry,
  mini = false,
  unavailable,
}: {
  entry: CoverEntry;
  mini?: boolean;
  unavailable?: () => void;
}) {
  const [failed, setFailed] = useState("");
  const url = entry.cover_url;
  if (!url || failed === url)
    return (
      <span
        className={`cover-review-empty ${mini ? "is-mini" : ""}`}
        role={mini ? undefined : "img"}
        aria-hidden={mini || undefined}
        aria-label={
          mini
            ? undefined
            : `${entry.facts.reasons.includes("missing") ? "No current cover" : "Current cover unavailable"} for ${title(entry)}`
        }
      >
        {!mini && (
          <span>
            {entry.facts.reasons.includes("missing")
              ? "No current cover"
              : "Current cover unavailable"}
          </span>
        )}
      </span>
    );
  return (
    <img
      src={entry.cover_url!}
      alt={mini ? "" : `Current cover of ${title(entry)}`}
      loading={mini ? "lazy" : "eager"}
      decoding="async"
      onError={() => {
        setFailed(url);
        unavailable?.();
      }}
    />
  );
}
function CoverTile({
  entry,
  active,
  suggestion,
  loading,
  error,
  focus,
  preview,
  choose,
  skip,
  pending,
}: {
  entry: CoverEntry;
  active: boolean;
  suggestion: Suggestion | null;
  loading: boolean;
  error: boolean;
  focus: () => void;
  preview: () => void;
  choose: () => void;
  skip: () => void;
  pending: boolean;
}) {
  const [failed, setFailed] = useState("");
  const art = suggestion && failed !== suggestion.url ? suggestion : null;
  const [currentFailed, setCurrentFailed] = useState(false);
  const canPreview =
    !!entry.cover_url && entry.facts.status === "known" && !currentFailed;
  return (
    <article
      id={`cover-art-${entry.id}`}
      tabIndex={0}
      onFocus={focus}
      className={`cover-review-tile ${active ? "is-active" : ""}`}
      aria-labelledby={`cover-title-${entry.id}`}
    >
      <button
        className="cover-review-art"
        id={`cover-choose-${entry.id}`}
        aria-label={`Choose a cover for ${title(entry)}`}
        onClick={choose}
      >
        {art ? (
          <img
            src={art.url}
            width={art.width}
            height={art.height}
            alt={`Suggested catalogue cover for ${title(entry)}`}
            loading="lazy"
            decoding="async"
            onError={() => setFailed(art.url)}
          />
        ) : (
          <CurrentArt key={`${entry.id}-${entry.revision}`} entry={entry} />
        )}
      </button>
      <p className="cover-review-suggestion">
        {entry.state === "done"
          ? "Current cover"
          : art
            ? "Suggested replacement · Catalogue"
            : loading
              ? "Checking local catalogue…"
              : "No suggestion yet"}
      </p>
      <h2 id={`cover-title-${entry.id}`}>{title(entry)}</h2>
      <p className="cover-review-author">
        {entry.authors.join(", ") || "Author not recorded"}
      </p>
      <div className="cover-review-current">
        {canPreview ? (
          <button
            id={`cover-preview-${entry.id}`}
            className="cover-review-thumb"
            onClick={preview}
            aria-label={`Preview current cover for ${title(entry)}`}
          >
            <CurrentArt
              entry={entry}
              mini
              unavailable={() => setCurrentFailed(true)}
            />
          </button>
        ) : (
          <span className="cover-review-thumb">
            <CurrentArt entry={{ ...entry, cover_url: null }} mini />
          </span>
        )}
        <span>{reason(entry)}</span>
      </div>
      {entry.selection_pending && (
        <p className="cover-review-changed">Selected; awaiting approval</p>
      )}
      {entry.selection_pending && (
        <button className="secondary" onClick={choose}>
          Review selected cover
        </button>
      )}
      {entry.changed_since_skipped && (
        <p className="cover-review-changed">Cover changed since skipped</p>
      )}
      {error && (
        <p className="cover-review-unavailable">
          Catalogue suggestion unavailable
        </p>
      )}
      {entry.state !== "done" && (
        <button
          className="cover-review-skip"
          disabled={pending}
          onClick={skip}
          aria-label={`${entry.state === "skipped" ? "Unskip" : "Skip"} ${title(entry)}`}
        >
          {entry.state === "skipped" ? "Unskip" : "Skip"}
        </button>
      )}
    </article>
  );
}
function censusMessage(data: CoverQueue): string {
  const census = data.census;
  if (!census)
    return "Covers have not been checked. Check again to start a library-wide check.";
  if (census.state === "pending")
    return "Cover check queued. Saved observations remain available.";
  if (census.state === "running")
    return `Checking covers: ${census.scanned} of ${census.total} observed. ${census.remaining} remaining.${census.error ? " Library access is interrupted; the check will retry." : ""}`;
  if (census.state === "failed")
    return "Cover check failed. Results are incomplete. Check again to retry.";
  if (census.state === "cancelled")
    return "Cover check stopped. Results are incomplete. Check again to continue.";
  if (census.state === "partial")
    return `Partial cover check. ${census.unresolved} could not be checked; ${census.remaining} remaining.${census.identity_issue_count ? ` ${census.identity_issue_count} book identities need attention.` : ""} Check again to retry.`;
  return data.stale
    ? "Library changed since the last cover check. Check again for current results."
    : `Check complete. ${census.scanned} books checked. Done means a previously flagged cover now passes this check.`;
}
function Preview({ entry, close }: { entry: CoverEntry; close: () => void }) {
  const dialog = useRef<HTMLDialogElement>(null);
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => {
      if (element.open) element.close();
    };
  }, []);
  return (
    <dialog
      ref={dialog}
      className="cover-review-preview"
      aria-labelledby="cover-preview-title"
      onClose={close}
      onCancel={close}
    >
      <div className="cover-review-preview-heading">
        <h2 id="cover-preview-title">{title(entry)}</h2>
        <button onClick={close} autoFocus>
          Close preview
        </button>
      </div>
      <p>Current cover · {reason(entry)}</p>
      <div className="cover-review-preview-art">
        <CurrentArt entry={entry} />
      </div>
    </dialog>
  );
}
export function CoverReview({
  session,
  route,
  navigate,
}: {
  session?: { csrf: string };
  route: CoverRoute;
  navigate: (patch: Partial<CoverRoute>) => void;
}) {
  const state: ReviewState =
    route.crs === "done" || route.crs === "skipped" ? route.crs : "todo";
  const client = useQueryClient();
  const [active, setActive] = useState("");
  const [picker, setPicker] = useState<CoverEntry | null>(null);
  const [preview, setPreview] = useState<CoverEntry | null>(null);
  const [notice, setNotice] = useState("");
  const [failedIntent, setFailedIntent] = useState<SkipIntent | null>(null);
  const inFlight = useRef(false);
  const pageFocus = useRef<"first" | "last" | null>(null);
  const scanKey = useRef<string | null>(null);
  const query = useQuery({
    queryKey: ["cover-reviews", state, route.crr, route.crp],
    queryFn: ({ signal }) =>
      fetchQueue(state, state === "done" ? "" : route.crr, route.crp, signal),
    enabled: !!session,
    retry: false,
    refetchInterval: (q) =>
      q.state.error
        ? false
        : ["pending", "running"].includes(q.state.data?.census?.state ?? "")
          ? 2000
          : 15_000,
  });
  const catalogue = useQuery({
    queryKey: ["cover-catalogue-pin"],
    queryFn: async ({ signal }) => {
      const data = await api<{
        status: string;
        version?: string;
        sha256?: string;
      }>("catalogue", { signal });
      return data.status === "ready" &&
        typeof data.version === "string" &&
        typeof data.sha256 === "string" &&
        /^[a-f0-9]{64}$/.test(data.sha256)
        ? { version: data.version, sha256: data.sha256 }
        : null;
    },
    enabled: !!session,
    retry: false,
  });
  const rows = query.data?.entries ?? [];
  const suggestions = useQuery({
    queryKey: [
      "cover-suggestions",
      query.data?.inventory,
      catalogue.data,
      rows.map((e) => [e.id, e.revision]),
    ],
    queryFn: ({ signal }) =>
      fetchSuggestions(rows, query.data!.inventory, catalogue.data!, signal),
    enabled:
      !!session &&
      !!catalogue.data &&
      !!query.data &&
      rows.length > 0 &&
      state !== "done",
    retry: false,
    staleTime: 60_000,
  });
  useEffect(() => {
    if (query.dataUpdatedAt || query.errorUpdatedAt)
      void client.invalidateQueries({ queryKey: ["cover-catalogue-pin"] });
  }, [query.dataUpdatedAt, query.errorUpdatedAt, client]);
  useEffect(() => {
    if (
      suggestions.error instanceof ApiError &&
      suggestions.error.status === 409
    )
      void client.invalidateQueries({ queryKey: ["cover-catalogue-pin"] });
  }, [suggestions.errorUpdatedAt, suggestions.error, client]);
  useEffect(() => {
    if (state === "done" && route.crr) navigate({ crr: "" });
  }, [state, route.crr, navigate]);
  const focused = rows.find((e) => e.id === active) ?? rows[0];
  useEffect(() => {
    if (!query.data) return;
    if (query.data.page > query.data.pages) {
      navigate({ crp: query.data.pages });
      return;
    }
    if (pageFocus.current && query.data.entries.length) {
      const entry =
        pageFocus.current === "last"
          ? query.data.entries.at(-1)!
          : query.data.entries[0];
      pageFocus.current = null;
      setActive(entry.id);
      document.getElementById(`cover-art-${entry.id}`)?.focus();
    }
  }, [query.data, navigate]);
  const changing = query.isError || (query.isFetching && !query.data);
  const skip = useMutation({
    mutationFn: async (intent: SkipIntent) => {
      const result = decodeEntry(
        await api<unknown>(`cover-reviews/${intent.entry.id}/skip`, {
          method: "POST",
          headers: {
            "X-CSRFToken": session!.csrf,
            "Idempotency-Key": intent.key,
          },
          body: JSON.stringify({
            revision: intent.entry.revision,
            skipped: intent.skipped,
          }),
        }),
      );
      if (
        result.id !== intent.entry.id ||
        result.book_uuid !== intent.entry.book_uuid ||
        result.library_uuid !== intent.entry.library_uuid ||
        result.revision !== intent.entry.revision + 1 ||
        result.state !==
          (intent.skipped
            ? "skipped"
            : result.facts.status === "known" && !result.facts.reasons.length
              ? "done"
              : "todo")
      )
        throw new Error(
          "The skip reply could not be verified. Refresh the review.",
        );
      return result;
    },
    onSuccess: async (_, intent) => {
      setFailedIntent(null);
      setNotice(
        `${title(intent.entry)} ${intent.skipped ? "skipped" : "returned to review"}.`,
      );
      const index = rows.findIndex((e) => e.id === intent.entry.id),
        next = rows[index + 1] ?? rows[index - 1];
      setActive(next?.id ?? "");
      await client.invalidateQueries({ queryKey: ["cover-reviews"] });
      requestAnimationFrame(() =>
        document
          .getElementById(`cover-art-${next?.id}`)
          ?.focus({ preventScroll: true }),
      );
    },
    onError: (_, intent) => {
      setFailedIntent(intent);
    },
    onSettled: () => {
      inFlight.current = false;
    },
  });
  const scan = useMutation({
    mutationFn: async () => {
      scanKey.current ??= crypto.randomUUID();
      const census = decodeCensus(
        await api<unknown>("cover-reviews/census", {
          method: "POST",
          headers: {
            "X-CSRFToken": session!.csrf,
            "Idempotency-Key": scanKey.current,
          },
          body: "{}",
        }),
      );
      if (!census)
        throw new Error(
          "The cover check could not be verified. Retry Check again.",
        );
      return census;
    },
    onSuccess: async () => {
      scanKey.current = null;
      setNotice("Cover check requested.");
      await client.invalidateQueries({ queryKey: ["cover-reviews"] });
      await client.invalidateQueries({ queryKey: ["cover-suggestions"] });
      await catalogue.refetch();
    },
    onError: async (error) => {
      if (error instanceof ApiError && error.code === "busy") {
        scanKey.current = null;
        await query.refetch();
      }
    },
  });
  function act(entry: CoverEntry) {
    if (!session || inFlight.current || changing || failedIntent) return;
    inFlight.current = true;
    skip.mutate({
      entry,
      skipped: entry.state !== "skipped",
      key: crypto.randomUUID(),
    });
  }
  function move(delta: number) {
    if (!focused) return;
    const next = rows[rows.indexOf(focused) + delta];
    if (next) {
      setActive(next.id);
      document.getElementById(`cover-art-${next.id}`)?.focus();
    } else if (
      query.data &&
      ((delta > 0 && route.crp < query.data.pages) ||
        (delta < 0 && route.crp > 1))
    ) {
      pageFocus.current = delta > 0 ? "first" : "last";
      navigate({ crp: route.crp + delta });
    }
  }
  function select(patch: Partial<CoverRoute>) {
    if (skip.isPending) return;
    pageFocus.current = null;
    setActive("");
    setNotice("");
    setFailedIntent(null);
    skip.reset();
    navigate({
      ...patch,
      ...(patch.crs === "done" ? { crr: "" } : {}),
      crp: 1,
    });
  }
  async function refreshReview() {
    const result = await query.refetch();
    if (!result.error) {
      setFailedIntent(null);
      skip.reset();
      requestAnimationFrame(() =>
        document
          .getElementById(`cover-art-${focused?.id}`)
          ?.focus({ preventScroll: true }),
      );
    }
  }
  const activeCensus = ["pending", "running"].includes(
    query.data?.census?.state ?? "",
  );
  return (
    <section
      className="cover-review"
      aria-label="Cover review"
      onKeyDown={(event) => {
        if (
          preview ||
          picker ||
          event.shiftKey ||
          event.altKey ||
          event.ctrlKey ||
          event.metaKey ||
          (event.target instanceof HTMLElement &&
            (event.target.matches("input, textarea, select") ||
              event.target.isContentEditable))
        )
          return;
        const target = event.target;
        const tile =
          target instanceof HTMLElement
            ? target.closest(".cover-review-tile")
            : null;
        const wall =
          target instanceof HTMLElement &&
          target.classList.contains("cover-review-wall");
        if (!tile && !wall) return;
        if (event.key === "ArrowLeft" || event.key === "ArrowRight") {
          event.preventDefault();
          move(event.key === "ArrowLeft" ? -1 : 1);
        }
        if (
          event.key.toLowerCase() === "s" &&
          tile &&
          focused &&
          focused.state !== "done"
        ) {
          event.preventDefault();
          act(focused);
        }
      }}
    >
      <div className="cover-review-heading">
        <div>
          <h1>Covers to review</h1>
          <p>Missing, generated and small covers, together.</p>
        </div>
        <button
          className="secondary"
          disabled={!session || scan.isPending || activeCensus}
          onClick={() => scan.mutate()}
        >
          {scan.isPending || activeCensus ? "Checking covers…" : "Check again"}
        </button>
      </div>
      {!session && (
        <p role="status">Sign in as an operator to review covers.</p>
      )}
      <div className="cover-review-toolbar">
        <nav aria-label="Cover queues">
          {states.map(([value, label]) => (
            <button
              key={value}
              aria-current={state === value ? "page" : undefined}
              disabled={skip.isPending}
              onClick={() => select({ crs: value === "todo" ? "" : value })}
            >
              {label} <span>{query.data?.counts[value] ?? "—"}</span>
            </button>
          ))}
        </nav>
        {state !== "done" && (
          <label>
            Show{" "}
            <select
              value={route.crr}
              onChange={(e) => select({ crr: e.target.value })}
              disabled={skip.isPending}
            >
              <option value="">All reasons</option>
              <option value="missing">Missing</option>
              <option value="generated">Generated</option>
              <option value="small">Small</option>
              <option value="width_below_1000">Below 1000 px wide</option>
              <option value="height_below_1200">Below 1200 px high</option>
              <option value="blank">Blank</option>
              <option value="unresolved">Could not be checked</option>
            </select>
          </label>
        )}
      </div>
      <p
        className="cover-review-status"
        role="status"
        data-testid="cover-census-status"
      >
        {query.data
          ? censusMessage(query.data)
          : query.isPending && session
            ? "Loading saved cover observations…"
            : "Cover observations unavailable."}
      </p>
      <p className="sr-only" role="status">
        {notice}
      </p>
      {query.isError && (
        <div className="error" role="alert">
          Cover reviews could not be refreshed. Saved observations may be out of
          date.{" "}
          <button onClick={() => void query.refetch()}>Retry reviews</button>
        </div>
      )}
      {scan.isError && (
        <div className="error" role="alert">
          {scan.error instanceof ApiError && scan.error.code === "busy"
            ? "Another cover check is running. Refresh reviews to see its progress."
            : "Cover check could not be started. Check again to retry."}
        </div>
      )}
      {skip.isError && (
        <div className="error" role="alert">
          {skip.error instanceof ApiError && skip.error.status === 409
            ? "This review changed on another device or in the library. Refresh before trying again."
            : "Skip was not confirmed. Your current book stays here."}{" "}
          <button onClick={() => void refreshReview()}>Refresh review</button>
          {!(skip.error instanceof ApiError && skip.error.status < 500) &&
            failedIntent && (
              <button
                onClick={() => {
                  if (!inFlight.current) {
                    inFlight.current = true;
                    skip.mutate(failedIntent);
                  }
                }}
              >
                Retry skip
              </button>
            )}
        </div>
      )}
      <div className="cover-review-navigation">
        <div>
          <button
            aria-label="Previous book"
            disabled={
              !focused || (rows.indexOf(focused) === 0 && route.crp === 1)
            }
            onClick={() => move(-1)}
          >
            Previous
          </button>
          <button
            aria-label="Next book"
            disabled={
              !focused ||
              (rows.indexOf(focused) === rows.length - 1 &&
                route.crp >= (query.data?.pages ?? 1))
            }
            onClick={() => move(1)}
          >
            Next
          </button>
        </div>
      </div>
      <div className="cover-review-wall">
        {rows.map((entry) => (
          <CoverTile
            key={`${entry.id}-${entry.revision}`}
            entry={entry}
            active={focused?.id === entry.id}
            suggestion={
              suggestions.isError || catalogue.isError
                ? null
                : (suggestions.data?.[entry.id] ?? null)
            }
            loading={suggestions.isFetching}
            error={suggestions.isError || catalogue.isError}
            focus={() => setActive(entry.id)}
            preview={() => {
              setActive(entry.id);
              setPreview(entry);
            }}
            choose={() => {
              setActive(entry.id);
              setPicker(entry);
            }}
            skip={() => act(entry)}
            pending={skip.isPending || changing || !!failedIntent}
          />
        ))}
      </div>
      {query.data && !rows.length && (
        <p className="cover-review-empty-queue">
          {state === "done"
            ? "No previously flagged covers pass the check yet."
            : state === "skipped"
              ? "No skipped covers in this view."
              : route.crr
                ? "No saved observations for this reason."
                : query.data.census?.complete && !query.data.stale
                  ? "No covers need attention."
                  : "No cover observations to show yet. Results are incomplete."}
        </p>
      )}
      {query.data && query.data.pages > 1 && (
        <nav className="cover-review-pagination" aria-label="Cover pages">
          <button
            disabled={route.crp <= 1 || skip.isPending}
            onClick={() => navigate({ crp: route.crp - 1 })}
          >
            Previous page
          </button>
          <span>
            Page {route.crp} of {query.data.pages}
          </span>
          <button
            disabled={route.crp >= query.data.pages || skip.isPending}
            onClick={() => navigate({ crp: route.crp + 1 })}
          >
            Next page
          </button>
        </nav>
      )}
      <details className="cover-review-keys">
        <summary>Keyboard shortcuts</summary>
        <p>
          Within the wall, Left / Right: previous or next book, across pages. S:
          skip or unskip the focused book. Escape: close the current-cover
          preview. Shortcuts pause while typing.
        </p>
      </details>
      {picker && session && query.data && (
        <CoverPicker
          key={picker.id}
          entry={picker}
          inventory={query.data.inventory}
          pin={catalogue.data ?? null}
          csrf={session.csrf}
          saved={() => {
            void client.invalidateQueries({ queryKey: ["cover-reviews"] });
          }}
          close={() => {
            const id = picker.id;
            setPicker(null);
            requestAnimationFrame(() =>
              document
                .getElementById(`cover-choose-${id}`)
                ?.focus({ preventScroll: true }),
            );
          }}
        />
      )}
      {preview && (
        <Preview
          entry={preview}
          close={() => {
            const id = preview.id;
            setPreview(null);
            requestAnimationFrame(() =>
              document
                .getElementById(`cover-preview-${id}`)
                ?.focus({ preventScroll: true }),
            );
          }}
        />
      )}
    </section>
  );
}
