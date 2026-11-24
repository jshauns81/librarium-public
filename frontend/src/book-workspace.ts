import { createContext, useContext } from "react";
import { api } from "./api";
import { assessmentJobBinds } from "./candidate-assessment-api";
import { isRetiredKind } from "./retired-kinds";
import type { Job } from "./types";

// Selections a workspace can still make: an EPUBCheck and an assessment.
export const workspaceKeys = ["fv", "fa"] as const;
export type WorkspaceKey = (typeof workspaceKeys)[number];
export type WorkspaceSelection = Record<WorkspaceKey, string | null>;
export type WorkspaceRoute = Partial<Record<WorkspaceKey, string>>;
export const emptyWorkspaceSelection: WorkspaceSelection = {
  fv: null,
  fa: null,
};
export const clearWorkspace = {
  fv: "",
  fa: "",
};
export type RecordedOrigin = {
  library_uuid: string | null;
  book_id: string;
  inventory: string;
  format: "EPUB";
};
export type Workspace = {
  schema_version: "librarium.book-workspace.v1";
  source: Job;
  origin: RecordedOrigin | null;
  selection: WorkspaceSelection;
  jobs: Job[];
};
const uuid = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/;
export class WorkspaceRefusal extends Error {}
const fail = () => {
  throw new WorkspaceRefusal(
    "These saved selections do not belong to this preserved book. Clear the selection and reopen its source history.",
  );
};
export function workspaceQuery(route: WorkspaceRoute) {
  const query = new URLSearchParams();
  for (const key of workspaceKeys)
    if (route[key]) {
      if (!uuid.test(route[key]!)) fail();
      query.set(key, route[key]!);
    }
  return query.toString();
}
// A saved workspace may still name a review copy, an output check or a delivery
// (selections and jobs of retired features). They are dropped, so the book opens
// at its nearest kept step: the inspection, or the selected assessment.
export function decodeWorkspace(
  value: unknown,
  sourceId: string,
  requested: WorkspaceRoute,
): Workspace {
  const data = value as Workspace;
  if (
    !data ||
    data.schema_version !== "librarium.book-workspace.v1" ||
    data.source?.id !== sourceId ||
    data.source.kind !== "epub" ||
    !data.selection ||
    !Array.isArray(data.jobs)
  )
    fail();
  const selection = { ...emptyWorkspaceSelection };
  for (const key of workspaceKeys) {
    const selected = data.selection[key] ?? null;
    if (
      selected !== null &&
      (typeof selected !== "string" || !uuid.test(selected))
    )
      fail();
    if (requested[key] && requested[key] !== selected) fail();
    selection[key] = selected;
  }
  const kinds: Record<WorkspaceKey, string> = {
    fv: "epub_validation",
    fa: "book_assessment",
  };
  const ids = new Set<string>();
  const jobs: Job[] = [];
  for (const job of data.jobs) {
    if (job && isRetiredKind(job.kind)) continue;
    if (
      !job ||
      !uuid.test(job.id) ||
      ids.has(job.id) ||
      job.source_job_id !== sourceId ||
      !Object.values(kinds).includes(job.kind ?? "")
    )
      fail();
    ids.add(job.id);
    if (job.kind === "book_assessment" && !assessmentJobBinds(data.source, job))
      fail();
    jobs.push(job);
  }
  for (const key of workspaceKeys)
    if (
      selection[key] &&
      !jobs.some((job) => job.id === selection[key] && job.kind === kinds[key])
    )
      fail();
  if (
    data.origin &&
    (data.origin.format !== "EPUB" ||
      (data.origin.library_uuid !== null &&
        (typeof data.origin.library_uuid !== "string" ||
          !data.origin.library_uuid ||
          Array.from(data.origin.library_uuid).length > 2000 ||
          /[\p{Cc}\p{Cs}]/u.test(data.origin.library_uuid))) ||
      !/^[1-9][0-9]*$/.test(data.origin.book_id) ||
      !/^[a-f0-9]{64}$/.test(data.origin.inventory))
  )
    fail();
  return {
    schema_version: data.schema_version,
    source: data.source,
    origin: data.origin ?? null,
    selection,
    jobs,
  };
}
export async function fetchWorkspace(
  source: string,
  route: WorkspaceRoute,
  signal: AbortSignal,
) {
  const query = workspaceQuery(route);
  const value = await api(
    `epub-inspections/${encodeURIComponent(source)}/workspace${query ? `?${query}` : ""}`,
    { signal },
  );
  try {
    return decodeWorkspace(value, source, route);
  } catch (error) {
    throw new WorkspaceRefusal(
      error instanceof Error
        ? error.message
        : "Saved workspace data could not be verified.",
    );
  }
}
export async function resolveWorkspace(job: string, signal?: AbortSignal) {
  if (!uuid.test(job)) fail();
  const value = await api<{
    schema_version: string;
    source_job_id: string;
    selection: WorkspaceSelection;
  }>(`book-workspaces/resolve?${new URLSearchParams({ job })}`, { signal });
  if (
    value.schema_version !== "librarium.book-workspace-resolution.v1" ||
    !uuid.test(value.source_job_id)
  )
    fail();
  workspaceQuery(
    Object.fromEntries(
      workspaceKeys.map((key) => [key, value.selection[key] ?? ""]),
    ),
  );
  return {
    fj: value.source_job_id,
    ...Object.fromEntries(
      workspaceKeys.map((key) => [key, value.selection[key] ?? ""]),
    ),
  } as { fj: string } & WorkspaceRoute;
}
export const BookWorkspaceContext = createContext<null | {
  value: Workspace;
  ready?: boolean;
  select: (
    pins: WorkspaceRoute & { fcw?: string; fcv?: string; fch?: string },
  ) => void;
}>(null);
export const useBookWorkspace = () => useContext(BookWorkspaceContext);
