import React, { useCallback, useEffect, useRef, useState } from "react";
import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { ApiError } from "./api";
import type { CataloguePin, CoverEntry } from "./cover-review-api";
import {
  fetchChoices,
  saveChoice,
  type CoverCandidate,
  type SelectionIntent,
} from "./cover-picker-api";
import "./cover-picker.css";
import { CoverSourceSearch } from "./CoverSourceSearch";

function Art({
  url,
  alt,
  empty,
  onError,
}: {
  url: string | null;
  alt: string;
  empty: string;
  onError?: () => void;
}) {
  const [failed, setFailed] = useState("");
  return url && failed !== url ? (
    <img
      src={url}
      alt={alt}
      onError={() => {
        setFailed(url);
        onError?.();
      }}
    />
  ) : (
    <span className="cover-picker-empty">{empty}</span>
  );
}
export function CoverPicker({
  entry,
  inventory,
  pin,
  csrf,
  close,
  saved,
}: {
  entry: CoverEntry;
  inventory: string;
  pin: CataloguePin | null;
  csrf: string;
  close: () => void;
  saved: () => void;
}) {
  const dialog = useRef<HTMLDialogElement>(null),
    back = useRef<HTMLButtonElement>(null),
    previewMode = useRef<"current" | "selected">("selected"),
    finishButton = useRef<HTMLButtonElement>(null),
    refreshButton = useRef<HTMLButtonElement>(null);
  const client = useQueryClient();
  const [selected, setSelected] = useState<CoverCandidate | null>(null),
    [view, setView] = useState<"compare" | "current" | "selected">("compare");
  const [failedImages, setFailedImages] = useState<Set<string>>(
      () => new Set(),
    ),
    [currentFailed, setCurrentFailed] = useState(false);
  const [failedIntent, setFailedIntent] = useState<SelectionIntent | null>(
    null,
  );
  const inFlight = useRef(false);
  const query = useQuery({
    queryKey: ["cover-choices", entry.id, entry.revision, inventory, pin],
    queryFn: ({ signal }) => fetchChoices(entry, inventory, pin!, signal),
    enabled: !!pin,
    retry: false,
    refetchOnWindowFocus: false,
    staleTime: 0,
  });
  const data = query.data;
  const order = useRef<string[]>([]);
  const incoming = data?.candidates ?? [];
  for (const c of incoming)
    if (!order.current.includes(c.id)) order.current.push(c.id);
  const candidates = [...incoming].sort((a, b) =>
    a.label === "Web" && b.label === "Web"
      ? (b.match ?? 0) - (a.match ?? 0) ||
        order.current.indexOf(a.id) - order.current.indexOf(b.id)
      : (a.label === "Web") !== (b.label === "Web")
        ? a.label === "Web"
          ? 1
          : -1
        : order.current.indexOf(a.id) - order.current.indexOf(b.id),
  );
  const searchChanged = useCallback(() => {
    void query.refetch();
  }, [query.refetch]);
  const selectable = candidates.filter((c) => c.selectable);
  const savedId =
    data?.selection?.status === "awaiting_approval"
      ? data.selection.candidate_id
      : null;
  function selectedChoice(c: CoverCandidate) {
    return (
      !!selected &&
      c.selectable &&
      (c.id === selected.id ||
        (selected.label === "Web" &&
          c.label === "Web" &&
          c.sha256 === selected.sha256))
    );
  }
  const requestedId = selected?.id ?? savedId ?? data?.default_candidate_id;
  const candidate =
    candidates.find((c) => c.id === requestedId) ??
    candidates.find(selectedChoice);
  const selectedId = candidate?.id ?? requestedId;
  const confirmed = !!savedId && selectedId === savedId;
  const mutation = useMutation({
    mutationFn: (intent: SelectionIntent) =>
      saveChoice(entry, inventory, pin!, csrf, intent),
    onSuccess: (result) => {
      setFailedIntent(null);
      requestAnimationFrame(() =>
        finishButton.current?.focus({ preventScroll: true }),
      );
      client.setQueryData(
        ["cover-choices", entry.id, entry.revision, inventory, pin],
        result,
      );
      saved();
    },
    onError: (_error, intent) => setFailedIntent(intent),
    onSettled: () => {
      inFlight.current = false;
    },
  });
  useEffect(() => {
    const element = dialog.current!;
    element.showModal();
    return () => {
      if (element.open) element.close();
    };
  }, []);
  useEffect(() => {
    if (mutation.isError) refreshButton.current?.focus({ preventScroll: true });
  }, [mutation.isError]);
  useEffect(() => {
    if (view !== "compare") back.current?.focus();
  }, [view]);
  function compare() {
    setView("compare");
    requestAnimationFrame(() =>
      dialog.current
        ?.querySelector<HTMLButtonElement>(
          `[data-preview="${previewMode.current}"]`,
        )
        ?.focus({ preventScroll: true }),
    );
  }
  function preview(mode: "current" | "selected") {
    previewMode.current = mode;
    setView(mode);
  }
  function pick(c: CoverCandidate) {
    if (!c.selectable || mutation.isPending || failedIntent) return;
    setSelected(c);
    mutation.reset();
  }
  async function refresh() {
    const result = await query.refetch();
    if (!result.error) {
      setFailedIntent(null);
      mutation.reset();
      if (selected && !result.data?.candidates.some(selectedChoice))
        setSelected(null);
    }
  }
  const canSave =
    !!candidate?.selectable &&
    !failedImages.has(candidate.id) &&
    !query.isError &&
    !query.isFetching &&
    !failedIntent &&
    !mutation.isPending &&
    entry.facts.status === "known";
  function submit() {
    if (!canSave || inFlight.current) return;
    inFlight.current = true;
    mutation.mutate({
      candidate_id: candidate!.id,
      selection_id: data?.selection?.id ?? null,
      key: crypto.randomUUID(),
    });
  }
  return (
    <dialog
      ref={dialog}
      className="cover-picker"
      aria-labelledby="cover-picker-title"
      onCancel={(event) => {
        event.preventDefault();
        if (view !== "compare") compare();
        else close();
      }}
      onKeyDown={(event) => {
        event.stopPropagation();
        if (event.key === "Tab") {
          const focusable = Array.from(
            dialog.current!.querySelectorAll<HTMLElement>(
              'button:not(:disabled), a[href], summary, input, select, textarea, [tabindex="0"]',
            ),
          ).filter(
            (el) =>
              (!el.closest("[hidden]") && !el.closest("details:not([open])")) ||
              el.tagName === "SUMMARY",
          );
          const first = focusable[0],
            last = focusable.at(-1);
          if (event.shiftKey && document.activeElement === first) {
            event.preventDefault();
            last?.focus();
          } else if (!event.shiftKey && document.activeElement === last) {
            event.preventDefault();
            first?.focus();
          }
        }
        if (event.key === "Escape") {
          event.preventDefault();
          if (view !== "compare") compare();
          else close();
          return;
        }
        if (
          view !== "compare" ||
          event.repeat ||
          event.shiftKey ||
          event.altKey ||
          event.ctrlKey ||
          event.metaKey ||
          (event.target instanceof HTMLElement &&
            (event.target.matches("input,textarea,select") ||
              event.target.isContentEditable))
        )
          return;
        if (/^[1-9]$/.test(event.key)) {
          const c = selectable[Number(event.key) - 1];
          if (c) {
            event.preventDefault();
            pick(c);
          }
        }
      }}
    >
      <header className="cover-picker-heading">
        <div>
          <h2 id="cover-picker-title">Choose a cover</h2>
          <p>
            {entry.title || "Untitled book"}
            {entry.authors.length ? ` · ${entry.authors.join(", ")}` : ""}
          </p>
        </div>
        <button onClick={close} autoFocus aria-label="Close cover picker">
          Close
        </button>
      </header>
      <div className="cover-picker-body">
        {view !== "compare" ? (
          <section
            className="cover-picker-preview"
            aria-label={`${view === "current" ? "Current" : "Selected"} cover preview`}
          >
            <button ref={back} onClick={compare}>
              Back to comparison
            </button>
            <h3>
              {view === "current"
                ? "Current cover"
                : `${candidate?.label ?? "Selected"} cover`}
            </h3>
            <div className="cover-picker-preview-art">
              <Art
                url={
                  view === "current"
                    ? entry.cover_url
                    : (candidate?.url ?? null)
                }
                alt={`${view === "current" ? "Current" : "Selected"} cover of ${entry.title || "Untitled book"}`}
                empty="Image unavailable"
              />
            </div>
          </section>
        ) : (
          <>
            <div className="cover-picker-compare">
              <section aria-labelledby="cover-picker-current">
                <h3 id="cover-picker-current">Current cover</h3>
                <div className="cover-picker-plate">
                  <Art
                    url={entry.cover_url}
                    alt={`Current cover of ${entry.title || "Untitled book"}`}
                    empty={
                      entry.facts.reasons.includes("missing")
                        ? "No current cover"
                        : "Current cover unavailable"
                    }
                    onError={() => setCurrentFailed(true)}
                  />
                </div>
                {!entry.facts.reasons.includes("missing") && (
                  <p className="cover-picker-dimensions">
                    {entry.facts.width && entry.facts.height
                      ? `${entry.facts.width} × ${entry.facts.height} px`
                      : "Dimensions unavailable"}
                  </p>
                )}
                {entry.facts.reasons.includes("generated") && (
                  <p>Title and author only</p>
                )}
                {entry.cover_url && !currentFailed && (
                  <button
                    className="cover-picker-text"
                    data-preview="current"
                    onClick={() => preview("current")}
                  >
                    Preview current
                  </button>
                )}
              </section>
              <section aria-labelledby="cover-picker-selected">
                <h3 id="cover-picker-selected">Selected cover</h3>
                <div className="cover-picker-plate">
                  <Art
                    url={candidate?.url ?? null}
                    alt={`Selected ${candidate?.label.toLowerCase() ?? ""} cover of ${entry.title || "Untitled book"}`}
                    empty={
                      query.isPending && pin
                        ? "Loading catalogue choices…"
                        : "No cover selected"
                    }
                    onError={() =>
                      candidate &&
                      setFailedImages((prev) => new Set(prev).add(candidate.id))
                    }
                  />
                </div>
                {candidate && (
                  <>
                    <p className="cover-picker-dimensions">
                      {candidate.width} × {candidate.height} px ·{" "}
                      {candidate.label}
                    </p>
                    {(candidate.confidence === "possible" ||
                      candidate.catalogue_suggestion ||
                      !candidate.meets_width_floor) && (
                      <p className="cover-picker-method">
                        {candidate.catalogue_suggestion && (
                          <span>
                            Catalogue suggestion ·{" "}
                            {Math.round(
                              (candidate.catalogue_confidence ?? 0) * 100,
                            )}
                            % similarity. Check the title, author and edition
                            before saving.
                          </span>
                        )}
                        {candidate.catalogue_suggestion &&
                          !candidate.meets_width_floor && <br />}
                        {candidate.confidence === "possible" && (
                          <span>
                            Possible match. Check the title, author and edition
                            before saving.
                          </span>
                        )}
                        {candidate.confidence === "possible" &&
                          !candidate.meets_width_floor && <br />}
                        {!candidate.meets_width_floor &&
                          "Below the 1000 px width target"}
                      </p>
                    )}
                    <div className="cover-picker-selected-actions">
                      {!failedImages.has(candidate.id) && (
                        <button
                          className="cover-picker-text"
                          data-preview="selected"
                          onClick={() => preview("selected")}
                        >
                          Preview selected
                        </button>
                      )}
                      <details>
                        <summary>Source &amp; method</summary>
                        <p>
                          {candidate.source_name} ·{" "}
                          {candidate.method === "original"
                            ? "Original image"
                            : candidate.method === "web_original"
                              ? "Original artwork · metadata removed"
                              : `Stored enhancement · ${candidate.pipeline}`}
                          {candidate.method === "web_original" &&
                            ` · ${candidate.reach_method === "server_browser" ? "Server browser" : candidate.reach_method === "archive" ? "Archive" : candidate.reach_method === "image_url" ? "Image URL" : "Server API"}`}
                        </p>
                        {candidate.source_url && (
                          <a
                            href={candidate.source_url}
                            target="_blank"
                            rel="noreferrer"
                          >
                            View recorded source
                          </a>
                        )}
                      </details>
                    </div>
                  </>
                )}
              </section>
            </div>
            {(!pin || query.isError) && (
              <div
                role={query.isError ? "alert" : "status"}
                className="cover-picker-notice"
              >
                <p>
                  {!pin
                    ? "Catalogue choices are unavailable. Refresh the catalogue and reopen this picker."
                    : query.error?.message}
                </p>
                {pin && (
                  <button onClick={() => void refresh()}>
                    Refresh choices
                  </button>
                )}
              </div>
            )}
            {data && data.source.reason && (
              <p role="status">{data.source.reason}</p>
            )}
            {data?.selection?.status === "stale" && (
              <p role="status">{data.selection.reason}</p>
            )}
            {entry.facts.status === "unresolved" && (
              <p role="status">
                The current cover could not be checked. Run Check again before
                saving a selection.
              </p>
            )}
            {["Catalogue covers", "Web covers"].map((heading, group) => {
              const choices = candidates.filter(
                (c) => (c.method === "web_original") === (group === 1),
              );
              return (
                <React.Fragment key={heading}>
                  {!!choices.length && (
                    <section
                      className="cover-picker-choices"
                      aria-labelledby={`cover-picker-group-${group}`}
                    >
                      <div className="cover-picker-choices-heading">
                        <h3 id={`cover-picker-group-${group}`}>{heading}</h3>
                        <p className="cover-picker-key-hint">
                          Keys 1–9 select, never save
                        </p>
                      </div>
                      <div className="cover-picker-options">
                        {choices.map((c) => (
                          <div key={c.id} className="cover-picker-option">
                            <button
                              className="cover-picker-choice"
                              aria-pressed={selectedId === c.id}
                              disabled={
                                !c.selectable ||
                                mutation.isPending ||
                                !!failedIntent
                              }
                              onClick={() => pick(c)}
                            >
                              <Art
                                url={c.url}
                                alt=""
                                empty="Image unavailable"
                              />
                              <span>
                                <strong>
                                  {c.selectable &&
                                    selectable.indexOf(c) < 9 && (
                                      <span className="cover-picker-key">
                                        {selectable.indexOf(c) + 1}{" "}
                                      </span>
                                    )}{" "}
                                  {c.label === "Web" ? c.source_name : c.label}
                                </strong>
                                <span>
                                  {c.width} × {c.height} px
                                </span>
                                {c.confidence === "possible" && (
                                  <span>
                                    Possible match
                                    {c.match != null
                                      ? ` · ${Math.round(c.match * 100)}% title/author similarity`
                                      : ""}
                                  </span>
                                )}
                                {c.catalogue_suggestion && (
                                  <span>
                                    Catalogue suggestion ·{" "}
                                    {Math.round(
                                      (c.catalogue_confidence ?? 0) * 100,
                                    )}
                                    % similarity
                                  </span>
                                )}
                                {c.catalogue_suggestion && (
                                  <span>{c.title}</span>
                                )}
                                {!c.selectable && <span>{c.reason}</span>}
                              </span>
                            </button>
                            <details>
                              <summary>
                                {c.selectable
                                  ? "Why this cover?"
                                  : "Why is this blocked?"}
                              </summary>
                              <p>{c.reason}</p>
                              {!c.selectable && <p>{c.title}</p>}
                            </details>
                          </div>
                        ))}
                      </div>
                    </section>
                  )}
                  {group === 0 && data && (
                    <CoverSourceSearch
                      entry={entry}
                      inventory={inventory}
                      pin={pin}
                      csrf={csrf}
                      enabled={data.web_sources_enabled ?? false}
                      changed={searchChanged}
                    />
                  )}
                </React.Fragment>
              );
            })}
          </>
        )}
        {mutation.isError && (
          <div role="alert" className="cover-picker-notice">
            <p>{mutation.error.message}</p>
            <button ref={refreshButton} onClick={() => void refresh()}>
              Refresh choices
            </button>
            {!(
              mutation.error instanceof ApiError && mutation.error.status < 500
            ) &&
              failedIntent && (
                <button
                  disabled={mutation.isPending}
                  onClick={() => {
                    if (!inFlight.current) {
                      inFlight.current = true;
                      mutation.mutate(failedIntent);
                    }
                  }}
                >
                  Retry selection
                </button>
              )}
          </div>
        )}
      </div>
      <footer className="cover-picker-footer">
        <p role="status">
          {mutation.isPending
            ? "Saving selection…"
            : confirmed
              ? "Selected; awaiting approval"
              : "Your library has not been changed."}
        </p>
        <div>
          <button ref={finishButton} className="secondary" onClick={close}>
            {confirmed ? "Close picker" : "Cancel"}
          </button>
          {view === "compare" && !confirmed && candidate && (
            <button className="primary" disabled={!canSave} onClick={submit}>
              Use this cover
            </button>
          )}
        </div>
      </footer>
    </dialog>
  );
}
