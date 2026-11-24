import { api, LIBRARY_TIMEOUT } from "./api";

export const reviewReasons = [
  "missing",
  "generated",
  "blank",
  "width_below_1000",
  "height_below_1200",
] as const;
export type ReviewState = "todo" | "done" | "skipped";
export type CoverEntry = {
  isbn?: string;
  id: string;
  library_uuid: string;
  book_uuid: string;
  book_id: string;
  title: string | null;
  authors: string[];
  revision: number;
  state: ReviewState;
  selection_pending?: boolean;
  changed_since_skipped: boolean;
  cover_url: string | null;
  facts: {
    status: "known" | "unresolved";
    width: number | null;
    height: number | null;
    reasons: string[];
  };
};
export type Census = {
  id: string;
  state: string;
  total: number;
  scanned: number;
  remaining: number;
  unresolved: number;
  identity_issue_count: number;
  error: string;
  complete: boolean;
};
export type CoverQueue = {
  census: Census | null;
  inventory: string;
  stale: boolean;
  state: ReviewState;
  reason: string;
  page: number;
  page_size: number;
  pages: number;
  total: number;
  counts: Record<ReviewState, number>;
  entries: CoverEntry[];
};
export type CataloguePin = { version: string; sha256: string };
export type Suggestion = { url: string; width: number; height: number };
function invalid(): never {
  throw new Error(
    "Cover review response could not be verified. Retry the request.",
  );
}
function record(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || value.length > 4096) invalid();
  return value;
}
function count(value: unknown, min = 0): number {
  if (typeof value !== "number" || !Number.isSafeInteger(value) || value < min)
    invalid();
  return value;
}
function bool(value: unknown): boolean {
  if (typeof value !== "boolean") invalid();
  return value;
}
function state(value: unknown): ReviewState {
  if (value !== "todo" && value !== "done" && value !== "skipped") invalid();
  return value;
}
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
export function decodeEntry(value: unknown): CoverEntry {
  const row = record(value),
    facts = record(row.facts),
    id = text(row.id);
  if (
    !uuid.test(id) ||
    !Array.isArray(row.authors) ||
    row.authors.length > 64 ||
    !Array.isArray(facts.reasons) ||
    facts.reasons.some(
      (r) => !reviewReasons.includes(r as (typeof reviewReasons)[number]),
    ) ||
    !["known", "unresolved"].includes(String(facts.status))
  )
    invalid();
  const cover_url = row.cover_url === null ? null : text(row.cover_url);
  if (cover_url !== null && cover_url !== `/api/cover-reviews/${id}/cover`)
    invalid();
  return {
    id,
    library_uuid: text(row.library_uuid),
    book_uuid: text(row.book_uuid),
    book_id: text(row.book_id),
    title: row.title === null ? null : text(row.title),
    authors: row.authors.map(text),
    isbn: row.isbn === undefined ? "" : text(row.isbn),
    revision: count(row.revision, 1),
    state: state(row.state),
    selection_pending:
      row.selection_pending === undefined ? false : bool(row.selection_pending),
    changed_since_skipped: bool(row.changed_since_skipped),
    cover_url,
    facts: {
      status: facts.status as "known" | "unresolved",
      width: facts.width === null ? null : count(facts.width, 1),
      height: facts.height === null ? null : count(facts.height, 1),
      reasons: facts.reasons.map(text),
    },
  };
}
export function decodeCensus(value: unknown): Census | null {
  if (value === null) return null;
  const row = record(value);
  if (
    ![
      "pending",
      "running",
      "complete",
      "partial",
      "failed",
      "cancelled",
    ].includes(String(row.state))
  )
    invalid();
  const result = {
    id: text(row.id),
    state: text(row.state),
    total: count(row.total),
    scanned: count(row.scanned),
    remaining: count(row.remaining),
    unresolved: count(row.unresolved),
    identity_issue_count: count(row.identity_issue_count),
    error: text(row.error),
    complete: bool(row.complete),
  };
  if (
    !uuid.test(result.id) ||
    result.complete !== (result.state === "complete") ||
    (result.complete && (result.remaining || result.unresolved))
  )
    invalid();
  return result;
}
export function decodeQueue(value: unknown): CoverQueue {
  const row = record(value),
    counts = record(row.counts);
  if (!Array.isArray(row.entries) || row.entries.length > 24) invalid();
  return {
    census: decodeCensus(row.census),
    inventory: text(row.inventory),
    stale: bool(row.stale),
    state: state(row.state),
    reason: text(row.reason),
    page: count(row.page, 1),
    page_size: count(row.page_size, 1),
    pages: count(row.pages, 1),
    total: count(row.total),
    counts: {
      todo: count(counts.todo),
      done: count(counts.done),
      skipped: count(counts.skipped),
    },
    entries: row.entries.map(decodeEntry),
  };
}
export async function fetchQueue(
  state: ReviewState,
  reason: string,
  page: number,
  signal?: AbortSignal,
) {
  const result = decodeQueue(
    await api<unknown>(
      `cover-reviews?${new URLSearchParams({ state, reason, page: String(page) })}`,
      { signal },
    ),
  );
  if (
    result.state !== state ||
    result.reason !== reason ||
    result.page !== page
  )
    invalid();
  return result;
}
export async function fetchSuggestions(
  entries: CoverEntry[],
  inventory: string,
  pin: CataloguePin,
  signal: AbortSignal,
): Promise<Record<string, Suggestion | null>> {
  if (!entries.length || entries.length > 24) invalid();
  const params = new URLSearchParams({ inventory, ...pin });
  for (const entry of entries)
    params.append("entry", `${entry.id}:${entry.revision}`);
  const row = record(
    await api<unknown>(`cover-reviews/suggestions?${params}`, {
      signal,
      timeout: LIBRARY_TIMEOUT,
    }),
  );
  const snapshot = record(row.snapshot);
  if (
    row.inventory !== inventory ||
    snapshot.version !== pin.version ||
    snapshot.sha256 !== pin.sha256 ||
    !Array.isArray(row.entries) ||
    row.entries.length !== entries.length
  )
    invalid();
  const result: Record<string, Suggestion | null> = {};
  for (const value of row.entries) {
    const item = record(value),
      id = text(item.id);
    const entry = entries.find((e) => e.id === id);
    if (
      !entry ||
      Object.hasOwn(result, id) ||
      item.revision !== entry.revision ||
      item.book_id !== entry.book_id ||
      item.book_uuid !== entry.book_uuid ||
      item.library_uuid !== entry.library_uuid
    )
      invalid();
    if (item.cover === null) {
      result[id] = null;
      continue;
    }
    const work = text(item.work_id),
      art = record(item.cover),
      url = text(art.url),
      digest = text(art.sha256),
      parsed = new URL(url, location.origin);
    if (
      !/^[-a-zA-Z0-9_:]{1,80}$/.test(work) ||
      !/^[a-f0-9]{64}$/.test(digest) ||
      !url.startsWith("/api/catalogue/covers/") ||
      parsed.origin !== location.origin ||
      parsed.pathname !== `/api/catalogue/covers/${work}/${digest}` ||
      parsed.searchParams.get("version") !== pin.version ||
      parsed.searchParams.get("sha256") !== pin.sha256 ||
      url.includes("\\")
    )
      invalid();
    result[id] = {
      url,
      width: count(art.width, 1),
      height: count(art.height, 1),
    };
  }
  return result;
}
