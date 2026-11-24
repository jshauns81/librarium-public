// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { PackageComparison } from "../src/PackageComparison";
import type { AuthorEvidence } from "../src/author-groups-api";
import type { Job } from "../src/types";

const pin = { version: "2026.10.25.1", sha256: "c".repeat(64), fixture: true };
const author = { id: "1", name: "Fixture Author", version: pin.version };
const work = { id: "w_fixture", title: "Fixture Volume", authors: [author] };
const target = { work: work.id, version: pin.version, sha256: pin.sha256 };
const evidence: AuthorEvidence = {
  schema_version: "librarium.author-groups.v1",
  snapshot: pin,
  status: "available",
  truncated: false,
  groups: [
    {
      author,
      status: "complete",
      canonical_owners: 1,
      aliases: [{ name: "Fixture Pen Name", owners: 1 }],
      alias_count: 1,
      matched_aliases: [],
      matched_alias_count: 0,
    },
  ],
};
const source = (id = "source-a"): Job => ({
  id,
  kind: "epub",
  request_key: "fixture",
  work_id: "a".repeat(64),
  title: "Fixture.epub",
  state: "succeeded",
  revision: 4,
  checkpoint: 4,
  attempts: 1,
  message: "Saved",
  updated_at: "2026-10-25T00:00:00Z",
  source_version: "librarium.epub-structure.v2",
  source_sha256: "a".repeat(64),
  input_fingerprint: "b".repeat(64),
  result: { report_sha256: "d".repeat(64), ready: false },
});
let calls: URL[];
let intercept: (
  url: URL,
  init: RequestInit,
) => Response | Promise<Response> | undefined;
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
beforeEach(() => {
  calls = [];
  intercept = () => undefined;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      const url = new URL(input, location.origin);
      calls.push(url);
      const custom = intercept(url, init);
      if (custom) return custom;
      if (url.pathname === "/api/catalogue")
        return json({ status: "ready", ...pin, total: 1 });
      if (url.pathname === "/api/catalogue/works/w_fixture")
        return json({ ...work, snapshot: pin, author_evidence: evidence });
      if (url.pathname.endsWith("/comparison"))
        return json({ error: "Fixture comparison unavailable" }, 503);
      throw new Error(url.pathname);
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function view(job = source(), clearTarget = vi.fn()) {
  return (
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <PackageComparison job={job} target={target} clearTarget={clearTarget} />
    </QueryClientProvider>
  );
}

it("loads the discovered work from its exact pin and waits for explicit source comparison", async () => {
  render(view());
  const compare = await screen.findByRole("button", {
    name: "Compare selected catalogue work",
  });
  expect(calls.some((url) => url.pathname === "/api/catalogue")).toBe(false);
  expect(calls.some((url) => url.pathname.endsWith("/comparison"))).toBe(false);
  const read = calls.find((url) => url.pathname.includes("works/"))!;
  expect(Object.fromEntries(read.searchParams)).toEqual({
    version: pin.version,
    sha256: pin.sha256,
  });
  fireEvent.click(compare);
  await waitFor(() =>
    expect(calls.some((url) => url.pathname.endsWith("/comparison"))).toBe(
      true,
    ),
  );
  const request = calls.find((url) => url.pathname.endsWith("/comparison"))!;
  expect(request.pathname).toBe("/api/epub-inspections/source-a/comparison");
  expect(Object.fromEntries(request.searchParams)).toEqual({
    work: work.id,
    version: pin.version,
    sha256: pin.sha256,
    source_sha256: source().source_sha256,
    report_sha256: source().result.report_sha256,
  });
});

it("retries the selected pin after a conflict and only clears it on an explicit current-snapshot choice", async () => {
  const clear = vi.fn();
  intercept = (url) =>
    url.pathname.includes("works/")
      ? json({ error: "Selected snapshot changed" }, 409)
      : undefined;
  render(view(source(), clear));
  fireEvent.click(
    await screen.findByRole("button", { name: "Retry catalogue connection" }),
  );
  await waitFor(() =>
    expect(calls.filter((url) => url.pathname.includes("works/"))).toHaveLength(
      2,
    ),
  );
  expect(clear).not.toHaveBeenCalled();
  fireEvent.click(
    await screen.findByRole("button", { name: "Use current snapshot" }),
  );
  await screen.findByLabelText("Search catalogue titles or authors");
  expect(clear).toHaveBeenCalledOnce();
  expect(
    screen.queryByRole("button", { name: "Compare selected catalogue work" }),
  ).toBeNull();
});

it("refuses a changed pin or cross-version group before displaying the selected work", async () => {
  intercept = (url) =>
    url.pathname.includes("works/")
      ? json({
          ...work,
          snapshot: { ...pin, sha256: "e".repeat(64) },
          author_evidence: evidence,
        })
      : undefined;
  render(view());
  await screen.findByText(/unsupported author evidence/);
  expect(screen.queryByRole("heading", { name: work.title })).toBeNull();
  expect(calls.some((url) => url.pathname.endsWith("/comparison"))).toBe(false);
});

it.each([{}, null, 42, ["Title"]])(
  "refuses a malformed selected title (%j) without rendering a comparison action",
  async (title) => {
    intercept = (url) =>
      url.pathname.includes("works/")
        ? json({ ...work, title, snapshot: pin, author_evidence: evidence })
        : undefined;
    render(view());
    await screen.findByText(/unsupported author evidence/);
    expect(
      screen.queryByRole("button", { name: "Compare selected catalogue work" }),
    ).toBeNull();
  },
);

it("clears an externally discarded target and follows a later explicit target without reusing the old work", async () => {
  const clear = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false } },
  });
  const component = (selectedTarget: typeof target | undefined) => (
    <QueryClientProvider client={client}>
      <PackageComparison
        job={source()}
        target={selectedTarget}
        clearTarget={clear}
      />
    </QueryClientProvider>
  );
  const mounted = render(component(target));
  await screen.findByRole("button", {
    name: "Compare selected catalogue work",
  });
  mounted.rerender(component(undefined));
  await waitFor(() =>
    expect(
      screen.queryByRole("button", { name: "Compare selected catalogue work" }),
    ).toBeNull(),
  );
  expect(screen.queryByRole("heading", { name: work.title })).toBeNull();
  mounted.rerender(component(target));
  await screen.findByRole("button", {
    name: "Compare selected catalogue work",
  });
  expect(calls.filter((url) => url.pathname.includes("works/"))).toHaveLength(
    2,
  );
});

it("loads its target in StrictMode after the development cleanup cycle", async () => {
  render(<React.StrictMode>{view()}</React.StrictMode>);
  await screen.findByRole("button", {
    name: "Compare selected catalogue work",
  });
});

it("drops a stale target read when the selected source changes", async () => {
  let resolve: ((value: Response) => void) | undefined;
  let signal: AbortSignal | undefined;
  intercept = (url, init) => {
    if (!url.pathname.includes("works/") || resolve) return;
    signal = init.signal as AbortSignal;
    return new Promise<Response>((done) => {
      resolve = done;
    });
  };
  const mounted = render(view());
  await waitFor(() => expect(resolve).toBeDefined());
  mounted.rerender(view(source("source-b")));
  await screen.findByRole("button", {
    name: "Compare selected catalogue work",
  });
  expect(signal?.aborted).toBe(true);
  resolve!(
    json({
      ...work,
      title: "Stale target",
      snapshot: pin,
      author_evidence: evidence,
    }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("heading", { name: "Stale target" })).toBeNull(),
  );
  fireEvent.click(
    screen.getByRole("button", { name: "Compare selected catalogue work" }),
  );
  await waitFor(() =>
    expect(
      calls.some(
        (url) => url.pathname === "/api/epub-inspections/source-b/comparison",
      ),
    ).toBe(true),
  );
});
