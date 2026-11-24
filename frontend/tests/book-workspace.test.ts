import { describe, expect, it } from "vitest";
import {
  decodeWorkspace,
  emptyWorkspaceSelection,
  resolveWorkspace,
  workspaceQuery,
} from "../src/book-workspace";
import { RETIRED_KINDS } from "../src/retired-kinds";
import type { Job } from "../src/types";

const source = "11111111-1111-4111-8111-111111111111";
const validation = "22222222-2222-4222-8222-222222222222";
const retiredId = (n: number) => `33333333-3333-4333-8333-33333333333${n}`;
const job = (id: string, kind: Job["kind"], parent = source): Job => ({
  id,
  kind,
  request_key: id,
  work_id: "a".repeat(64),
  title: "Book",
  state: "succeeded",
  revision: 1,
  checkpoint: 4,
  attempts: 1,
  message: "Complete",
  result: {},
  updated_at: "2026-11-01T12:00:00Z",
  source_version: "librarium.epub-structure.v5",
  source_sha256: "a".repeat(64),
  input_fingerprint: "b".repeat(64),
  source_job_id: parent,
});
const sourceJob = { ...job(source, "epub"), source_job_id: undefined };
const assessment = "44444444-4444-4444-8444-444444444444";
const check = job(validation, "epub_validation");
const payload = () => ({
  schema_version: "librarium.book-workspace.v1",
  source: sourceJob,
  origin: null,
  selection: { ...emptyWorkspaceSelection, fv: validation },
  jobs: [check],
});
describe("exact book workspace relations", () => {
  it("keeps the supplied validation selection instead of choosing a latest record", () => {
    const decoded = decodeWorkspace(payload(), source, { fv: validation });
    expect(decoded.selection.fv).toBe(validation);
    expect(decoded.jobs).toEqual([check]);
  });
  it("retains a bounded opaque recorded library identity without requiring UUID syntax", () => {
    const origin = {
      library_uuid: "historical-library-identity",
      book_id: "23",
      inventory: "a".repeat(64),
      format: "EPUB",
    };
    expect(
      decodeWorkspace({ ...payload(), origin }, source, { fv: validation })
        .origin,
    ).toEqual(origin);
    expect(
      decodeWorkspace(
        { ...payload(), origin: { ...origin, library_uuid: null } },
        source,
        { fv: validation },
      ).origin,
    ).toEqual({ ...origin, library_uuid: null });
    for (const library_uuid of ["", "x".repeat(2001), "unsafe\u0000identity"])
      expect(() =>
        decodeWorkspace(
          { ...payload(), origin: { ...origin, library_uuid } },
          source,
          { fv: validation },
        ),
      ).toThrow();
  });
  it("rejects mismatched source headers and changed explicit selections", () => {
    expect(() =>
      decodeWorkspace(
        { ...payload(), source: { ...sourceJob, id: validation } },
        source,
        { fv: validation },
      ),
    ).toThrow();
    expect(() => decodeWorkspace(payload(), source, { fv: source })).toThrow();
  });
  it("requires complete related jobs and refuses absent bindings", () => {
    expect(() =>
      decodeWorkspace({ ...payload(), jobs: [] }, source, { fv: validation }),
    ).toThrow();
    expect(() =>
      decodeWorkspace(
        { ...payload(), jobs: [{ ...check, source_job_id: undefined }] },
        source,
        { fv: validation },
      ),
    ).toThrow();
  });
  it("rejects foreign job lineage and malformed routes before requesting", () => {
    expect(() =>
      decodeWorkspace(
        {
          ...payload(),
          jobs: [job(validation, "epub_validation", validation)],
        },
        source,
        { fv: validation },
      ),
    ).toThrow();
    expect(() => workspaceQuery({ fv: "../foreign" })).toThrow();
    expect(workspaceQuery({ fv: validation, fa: "" })).toBe(`fv=${validation}`);
  });
  it("sends no pin of a retired feature", () => {
    expect(
      workspaceQuery({ fg: retiredId(1), fd: retiredId(2) } as never),
    ).toBe("");
  });
});
describe("saved workspaces from retired review-copy and delivery features", () => {
  const retiredJobs = RETIRED_KINDS.map((kind, index) =>
    job(retiredId(index), kind),
  );
  const retired = {
    fg: retiredId(0),
    fo: retiredId(1),
    fov: retiredId(1),
    fdp: retiredId(2),
    fd: retiredId(3),
    fdj: retiredId(4),
    fda: retiredId(5),
    faj: retiredId(5),
  };
  it("opens at the inspection when only retired selections are named", () => {
    const decoded = decodeWorkspace(
      {
        ...payload(),
        selection: { ...retired },
        jobs: retiredJobs,
        output: { id: retiredId(1), generation_job_id: retiredId(0) },
        delivery: { id: retiredId(3), job_id: retiredId(3) },
      },
      source,
      {},
    );
    expect(decoded.selection).toEqual(emptyWorkspaceSelection);
    expect(decoded.jobs).toEqual([]);
    expect(decoded).not.toHaveProperty("output");
    expect(decoded).not.toHaveProperty("delivery");
  });
  it("keeps the validation beside retired records instead of refusing the book", () => {
    const decoded = decodeWorkspace(
      {
        ...payload(),
        selection: { ...retired, fv: validation },
        jobs: [...retiredJobs, check],
      },
      source,
      { fv: validation },
    );
    expect(decoded.selection.fv).toBe(validation);
    expect(decoded.jobs).toEqual([check]);
  });
  it("does not trust a retired record's shape", () => {
    const decoded = decodeWorkspace(
      {
        ...payload(),
        selection: { ...retired, fg: "not-a-uuid" },
        jobs: [
          { kind: "epub_correction" },
          { ...retiredJobs[3], source_job_id: undefined },
          check,
        ],
      },
      source,
      {},
    );
    expect(decoded.jobs).toEqual([check]);
  });
  it("still refuses a job of an unknown kind", () => {
    expect(() =>
      decodeWorkspace(
        { ...payload(), jobs: [check, job(retiredId(7), "synthetic")] },
        source,
        {},
      ),
    ).toThrow();
  });
  it("resolves a retired record to the nearest kept step", async () => {
    const original = globalThis.fetch;
    globalThis.fetch = (() =>
      Promise.resolve(
        new Response(
          JSON.stringify({
            schema_version: "librarium.book-workspace-resolution.v1",
            source_job_id: source,
            selection: { ...retired, fv: null, fa: assessment },
          }),
        ),
      )) as typeof fetch;
    try {
      const pins = await resolveWorkspace(retiredId(0));
      expect(pins).toEqual({ fj: source, fv: "", fa: assessment });
    } finally {
      globalThis.fetch = original;
    }
  });
});
