import { api, LIBRARY_TIMEOUT } from "./api";
import type { CataloguePin, CoverEntry } from "./cover-review-api";

export type CoverCandidate = {
  id: string;
  label: "Enhanced" | "Original" | "Web";
  title: string;
  catalogue_suggestion?: boolean;
  catalogue_confidence?: number;
  relationship?: "similar_metadata" | "contained_in";
  sha256: string;
  original_sha256: string;
  width: number;
  height: number;
  method: "original" | "stored_derivative" | "web_original";
  pipeline: string;
  url: string;
  selectable: boolean;
  meets_width_floor: boolean;
  reason: string;
  source_name: string;
  reach_method?:
    "server_api" | "server_browser" | "archive" | "image_url" | "stored";
  source_url: string | null;
  match?: number | null;
  confidence?: "possible" | "strong";
};
export type CoverSelection = {
  id: string;
  candidate_id: string;
  status: "awaiting_approval" | "stale";
  reason: string;
};
export type CoverChoices = {
  web_sources_enabled: boolean;
  entry_id: string;
  revision: number;
  inventory: string;
  snapshot: CataloguePin;
  policy: string;
  candidates: CoverCandidate[];
  default_candidate_id: string | null;
  selection: CoverSelection | null;
  source: { status: "complete" | "empty" | "unavailable"; reason: string };
};
const uuid = /^[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}$/;
const digest = /^[a-f0-9]{64}$/;
function invalid(): never {
  throw new Error("Cover choices could not be verified. Refresh the choices.");
}
function object(value: unknown): Record<string, unknown> {
  if (!value || typeof value !== "object" || Array.isArray(value)) invalid();
  return value as Record<string, unknown>;
}
function text(value: unknown): string {
  if (typeof value !== "string" || value.length > 4096) invalid();
  return value;
}
function id(value: unknown) {
  const result = text(value);
  if (!uuid.test(result)) invalid();
  return result;
}
function number(value: unknown) {
  if (!Number.isSafeInteger(value) || typeof value !== "number" || value < 1)
    invalid();
  return value;
}
function bool(value: unknown) {
  if (typeof value !== "boolean") invalid();
  return value;
}
export function decodeChoices(
  value: unknown,
  entry: CoverEntry,
  inventory: string,
  pin: CataloguePin,
): CoverChoices {
  const row = object(value),
    snapshot = object(row.snapshot),
    source = object(row.source);
  if (
    row.entry_id !== entry.id ||
    row.revision !== entry.revision ||
    row.library_uuid !== entry.library_uuid ||
    row.book_uuid !== entry.book_uuid ||
    row.inventory !== inventory ||
    snapshot.version !== pin.version ||
    snapshot.sha256 !== pin.sha256 ||
    row.policy !== "librarium.cover-choice.v1" ||
    !Array.isArray(row.candidates) ||
    row.candidates.length > 32 ||
    !["complete", "empty", "unavailable"].includes(String(source.status))
  )
    invalid();
  const seen = new Set<string>();
  const candidates = row.candidates.map((value): CoverCandidate => {
    const c = object(value),
      candidateId = id(c.id),
      sha = text(c.sha256),
      original = text(c.original_sha256),
      work = text(c.work_id),
      url = text(c.url),
      parsed = new URL(url, location.origin),
      web = c.method === "web_original";
    if (
      seen.has(candidateId) ||
      !digest.test(sha) ||
      !digest.test(original) ||
      !/^[-a-zA-Z0-9_:]{1,80}$/.test(work) ||
      !(web
        ? url.startsWith(`/api/cover-reviews/${entry.id}/images/`)
        : url.startsWith("/api/catalogue/covers/")) ||
      url.includes("\\") ||
      parsed.origin !== location.origin ||
      (web
        ? !new RegExp(
            `^/api/cover-reviews/${entry.id}/images/[a-f0-9-]{36}/${candidateId}$`,
          ).test(parsed.pathname)
        : parsed.pathname !== `/api/catalogue/covers/${work}/${sha}`) ||
      (!web && parsed.searchParams.get("version") !== pin.version) ||
      (!web && parsed.searchParams.get("sha256") !== pin.sha256) ||
      !["Original", "Enhanced", "Web"].includes(String(c.label)) ||
      !["original", "stored_derivative", "web_original"].includes(
        String(c.method),
      )
    )
      invalid();
    seen.add(candidateId);
    const enhanced = c.method === "stored_derivative";
    if (
      (c.label === "Enhanced") !== enhanced ||
      (c.label === "Web") !== web ||
      parsed.searchParams.get("variant") !== (enhanced ? "upscaled" : null) ||
      (!enhanced && !web && sha !== original)
    )
      invalid();
    const width = number(c.width),
      height = number(c.height);
    if (
      width > 20000 ||
      height > 20000 ||
      width * height > 25000000 ||
      c.meets_width_floor !== width >= 1000
    )
      invalid();
    const sourceUrl = c.source_url === null ? null : text(c.source_url);
    if (sourceUrl) {
      const origin = new URL(sourceUrl);
      if (
        origin.protocol !== "https:" ||
        origin.username ||
        origin.password ||
        (!web &&
          ![
            "wh40k.lexicanum.com",
            "whfb.lexicanum.com",
            "ageofsigmar.lexicanum.com",
          ].includes(origin.hostname))
      )
        invalid();
    }
    return {
      id: candidateId,
      label: c.label as CoverCandidate["label"],
      title: text(c.title),
      catalogue_suggestion:
        c.catalogue_suggestion === undefined
          ? false
          : bool(c.catalogue_suggestion),
      catalogue_confidence: (() => {
        if (c.catalogue_confidence === undefined) return undefined;
        if (
          typeof c.catalogue_confidence !== "number" ||
          !Number.isFinite(c.catalogue_confidence) ||
          c.catalogue_confidence < 0 ||
          c.catalogue_confidence > 1
        )
          invalid();
        return c.catalogue_confidence;
      })(),
      relationship:
        c.relationship === undefined
          ? undefined
          : ["similar_metadata", "contained_in"].includes(
                String(c.relationship),
              )
            ? (c.relationship as CoverCandidate["relationship"])
            : invalid(),
      sha256: sha,
      original_sha256: original,
      width,
      height,
      method: c.method as CoverCandidate["method"],
      pipeline: text(c.pipeline),
      url,
      selectable: bool(c.selectable),
      meets_width_floor: bool(c.meets_width_floor),
      reason: text(c.reason),
      source_name: text(c.source_name),
      reach_method: (() => {
        const method =
          c.reach_method ??
          (web
            ? c.source_name === "Lexicanum (archived copy)"
              ? "archive"
              : "server_api"
            : "stored");
        if (
          ![
            "server_api",
            "server_browser",
            "archive",
            "image_url",
            "stored",
          ].includes(String(method))
        )
          invalid();
        return method as CoverCandidate["reach_method"];
      })(),
      source_url: sourceUrl,
      ...(web
        ? (() => {
            const match = c.match ?? null;
            if (
              match !== null &&
              (typeof match !== "number" ||
                !Number.isFinite(match) ||
                match < 0 ||
                match > 1)
            )
              invalid();
            const confidence =
              match === null || match < 0.75 ? "possible" : "strong";
            return {
              match: match as number | null,
              confidence: confidence as "possible" | "strong",
            };
          })()
        : {}),
    };
  });
  const defaultId =
    row.default_candidate_id === null ? null : id(row.default_candidate_id);
  if (
    defaultId &&
    !candidates.some(
      (c) => c.id === defaultId && c.selectable && !c.catalogue_suggestion,
    )
  )
    invalid();
  let selection: CoverSelection | null = null;
  if (row.selection !== null) {
    const s = object(row.selection);
    if (!["awaiting_approval", "stale"].includes(String(s.status))) invalid();
    selection = {
      id: id(s.id),
      candidate_id: id(s.candidate_id),
      status: s.status as CoverSelection["status"],
      reason: text(s.reason),
    };
    if (
      selection.status === "awaiting_approval" &&
      !candidates.some((c) => c.id === selection!.candidate_id && c.selectable)
    )
      invalid();
  }
  return {
    web_sources_enabled: row.web_sources_enabled === true,
    entry_id: entry.id,
    revision: entry.revision,
    inventory,
    snapshot: pin,
    policy: text(row.policy),
    candidates,
    default_candidate_id: defaultId,
    selection,
    source: {
      status: source.status as CoverChoices["source"]["status"],
      reason: text(source.reason),
    },
  };
}
export async function fetchChoices(
  entry: CoverEntry,
  inventory: string,
  pin: CataloguePin,
  signal: AbortSignal,
) {
  return decodeChoices(
    await api<unknown>(
      `cover-reviews/${entry.id}/choices?${new URLSearchParams({ inventory, ...pin, revision: String(entry.revision) })}`,
      { signal, timeout: LIBRARY_TIMEOUT },
    ),
    entry,
    inventory,
    pin,
  );
}
export type SelectionIntent = {
  candidate_id: string;
  selection_id: string | null;
  key: string;
};
export async function saveChoice(
  entry: CoverEntry,
  inventory: string,
  pin: CataloguePin,
  csrf: string,
  intent: SelectionIntent,
) {
  const result = decodeChoices(
    await api<unknown>(`cover-reviews/${entry.id}/choices`, {
      method: "POST",
      headers: { "X-CSRFToken": csrf, "Idempotency-Key": intent.key },
      body: JSON.stringify({
        inventory,
        ...pin,
        revision: entry.revision,
        candidate_id: intent.candidate_id,
        selection_id: intent.selection_id,
      }),
      timeout: LIBRARY_TIMEOUT,
    }),
    entry,
    inventory,
    pin,
  );
  if (
    result.selection?.status !== "awaiting_approval" ||
    result.selection.candidate_id !== intent.candidate_id
  )
    invalid();
  return result;
}
