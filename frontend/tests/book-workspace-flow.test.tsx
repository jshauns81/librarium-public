// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  act,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { FileInspections, type FileRoute } from "../src/FileInspections";
import { emptyWorkspaceSelection } from "../src/book-workspace";
import type { Job } from "../src/types";
import { trackReturnIntent } from "../src/return-intent";
const a = "11111111-1111-4111-8111-111111111111",
  b = "22222222-2222-4222-8222-222222222222";
const source = (id: string): Job => ({
  id,
  kind: "epub",
  request_key: id,
  work_id: "a".repeat(64),
  title: id === a ? "Book A" : "Book B",
  state: "queued",
  revision: 1,
  checkpoint: 0,
  attempts: 0,
  message: "Queued",
  result: {},
  updated_at: "2026-11-01T12:00:00Z",
  source_version: "librarium.epub-structure.v5",
  source_sha256: "a".repeat(64),
  input_fingerprint: "b".repeat(64),
});
const payload = (id: string) => ({
  schema_version: "librarium.book-workspace.v1",
  source: source(id),
  origin: null,
  selection: emptyWorkspaceSelection,
  jobs: [],
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
});
function mount(
  initial: Partial<FileRoute> = {},
  extra: Partial<React.ComponentProps<typeof FileInspections>> = {},
) {
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  function Harness() {
    const [route, setRoute] = useState<FileRoute>({
      fj: a,
      fq: "",
      fs: "",
      fp: 1,
      ...initial,
    });
    return (
      <>
        <button onClick={() => setRoute({ ...route, fj: b })}>
          Open Book B
        </button>
        <FileInspections
          route={route}
          navigate={(next) => setRoute((old) => ({ ...old, ...next }))}
          session={{ csrf: "fixture", file_inspections: true }}
          sessionPending={false}
          sessionError={null}
          retrySession={() => {}}
          jobs={[source(a), source(b)]}
          merge={() => {}}
          cancel={() => {}}
          announceTerminal={() => {}}
          returnToReviews={() => {}}
          notify={() => {}}
          {...extra}
        />
      </>
    );
  }
  return render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <Harness />
    </QueryClientProvider>,
  );
}
it("waits for authoritative lineage before revealing the book and refuses a foreign response", async () => {
  let finish!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn(
      () =>
        new Promise<Response>((resolve) => {
          finish = resolve;
        }),
    ),
  );
  mount({ fv: b });
  expect(screen.queryByRole("heading", { name: "Book A" })).toBeNull();
  await act(async () => finish(new Response(JSON.stringify(payload(b)))));
  expect(
    await screen.findByRole("heading", {
      name: "Saved workspace could not open",
    }),
  ).toBeTruthy();
  expect(screen.queryByRole("heading", { name: "Book B" })).toBeNull();
  expect(screen.queryByLabelText("EPUB file")).toBeNull();
});
it("ignores a late source response after switching books and keeps unrelated uploads and history outside", async () => {
  let old!: (value: Response) => void;
  vi.stubGlobal(
    "fetch",
    vi.fn((url: string) =>
      url.includes(a)
        ? new Promise<Response>((resolve) => {
            old = resolve;
          })
        : Promise.resolve(new Response(JSON.stringify(payload(b)))),
    ),
  );
  mount();
  fireEvent.click(screen.getByRole("button", { name: "Open Book B" }));
  expect(await screen.findByRole("heading", { name: "Book B" })).toBeTruthy();
  await act(async () => old(new Response(JSON.stringify(payload(a)))));
  expect(screen.queryByRole("heading", { name: "Book A" })).toBeNull();
  expect(screen.getByRole("heading", { name: "Book B" })).toBeTruthy();
  expect(screen.queryByRole("link", { name: "Reference" })).toBeNull();
  expect(screen.queryByLabelText("EPUB file")).toBeNull();
  expect(
    screen.queryByRole("heading", { name: "File inspection history" }),
  ).toBeNull();
});
it("refuses malformed selections visibly without mounting a related panel and recovers only after explicit clearing", async () => {
  const fetcher = vi.fn(() =>
    Promise.resolve(new Response(JSON.stringify(payload(a)))),
  );
  vi.stubGlobal("fetch", fetcher);
  mount({ fa: "../other" });
  await screen.findByRole("heading", {
    name: "Saved workspace could not open",
  });
  expect(fetcher).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Clear related selections" }),
  );
  expect(await screen.findByRole("heading", { name: "Book A" })).toBeTruthy();
  await waitFor(() => expect(fetcher).toHaveBeenCalled());
});
it("keeps a comparison draft across a delayed unrelated source-validation selection", async () => {
  const checked = "33333333-3333-4333-8333-333333333333";
  const preserved = {
    ...source(a),
    state: "succeeded" as const,
    result: {
      report_sha256: "b".repeat(64),
      report_url: `/api/epub-inspections/${a}/report`,
    },
  };
  let finish!: (value: Response) => void;
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string) => {
      const url = new URL(input, location.origin);
      if (url.pathname.endsWith("/workspace")) {
        if (url.searchParams.has("fv"))
          return new Promise<Response>((resolve) => {
            finish = resolve;
          });
        return Promise.resolve(
          new Response(JSON.stringify({ ...payload(a), source: preserved })),
        );
      }
      if (url.pathname === "/api/catalogue")
        return Promise.resolve(
          new Response(
            JSON.stringify({
              status: "ready",
              version: "2026.10.24.2",
              sha256: "c".repeat(64),
              fixture: true,
              total: 1,
            }),
          ),
        );
      if (url.pathname.endsWith("/corrections"))
        return Promise.resolve(
          new Response(
            JSON.stringify({ results: [], count: 0, page: 1, pages: 1 }),
          ),
        );
      return Promise.resolve(
        new Response(JSON.stringify({ error: "Fixture not configured" }), {
          status: 404,
        }),
      );
    }),
  );
  function Harness() {
    const [route, setRoute] = useState<FileRoute>({
      fj: a,
      fq: "",
      fs: "",
      fp: 1,
    });
    return (
      <>
        <button onClick={() => setRoute({ ...route, fv: checked })}>
          Choose source validation
        </button>
        <FileInspections
          route={route}
          navigate={(next) => setRoute((old) => ({ ...old, ...next }))}
          session={{ csrf: "fixture", file_inspections: true }}
          sessionPending={false}
          sessionError={null}
          retrySession={() => {}}
          jobs={[preserved]}
          merge={() => {}}
          cancel={() => {}}
          announceTerminal={() => {}}
          returnToReviews={() => {}}
          notify={() => {}}
        />
      </>
    );
  }
  render(
    <QueryClientProvider
      client={
        new QueryClient({
          defaultOptions: { queries: { retry: false, gcTime: 0 } },
        })
      }
    >
      <Harness />
    </QueryClientProvider>,
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Compare with catalogue" }),
  );
  const draft = await screen.findByLabelText(
    "Search catalogue titles or authors",
  );
  draft.focus();
  fireEvent.change(draft, { target: { value: "unsaved comparison title" } });
  fireEvent.click(
    screen.getByRole("button", { name: "Choose source validation" }),
  );
  await waitFor(() => expect(finish).toBeTypeOf("function"));
  expect(draft.closest("[hidden], [inert]")).toBeNull();
  expect(document.activeElement).toBe(draft);
  expect(screen.getByRole("heading", { name: "Book A" })).toBeTruthy();
  await act(async () =>
    finish(
      new Response(
        JSON.stringify({
          ...payload(a),
          source: preserved,
          selection: { ...emptyWorkspaceSelection, fv: checked },
          jobs: [
            {
              ...preserved,
              id: checked,
              kind: "epub_validation",
              source_job_id: a,
            },
          ],
        }),
      ),
    ),
  );
  expect(
    (
      (await screen.findByLabelText(
        "Search catalogue titles or authors",
      )) as HTMLInputElement
    ).value,
  ).toBe("unsaved comparison title");
  expect(document.activeElement).toBe(draft);
});

it("keeps confirmed progress and cancellation available after a transient poll failure", async () => {
  let fail = false;
  const cancel = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(() =>
      Promise.resolve(
        fail
          ? new Response(JSON.stringify({ error: "Temporary read failure" }), {
              status: 503,
            })
          : new Response(JSON.stringify(payload(a))),
      ),
    ),
  );
  mount({}, { cancel });
  const button = await screen.findByRole("button", {
    name: "Cancel inspection",
  });
  button.focus();
  fail = true;
  await screen.findByText(/could not refresh/i, {}, { timeout: 4000 });
  expect(screen.getByRole("heading", { name: "Book A" })).toBeTruthy();
  expect(document.activeElement).toBe(button);
  fireEvent.click(button);
  expect(cancel).toHaveBeenCalledWith(expect.objectContaining({ id: a }));
});

it.each([false, true])(
  "restores workspace reference trigger after delayed source read without overriding newer input: %s",
  async (cancel) => {
    history.replaceState({ reviewOrigin: { jobId: a } }, "", location.pathname);
    let finish!: (value: Response) => void;
    vi.stubGlobal(
      "fetch",
      vi.fn((url: string) =>
        url.includes("/workspace")
          ? new Promise<Response>((resolve) => {
              finish = resolve;
            })
          : Promise.resolve(new Response("{}", { status: 404 })),
      ),
    );
    mount(
      {},
      {
        restoreWorkspace: { scroll: 420, focusId: "book-reference-browse" },
        browseReferences: vi.fn(),
      },
    );
    await waitFor(() => expect(finish).toBeTypeOf("function"));
    if (cancel) fireEvent.wheel(document);
    await act(async () => finish(new Response(JSON.stringify(payload(a)))));
    const trigger = await screen.findByRole("button", {
      name: "Browse reference catalogue",
    });
    await waitFor(() =>
      expect(document.activeElement === trigger).toBe(!cancel),
    );
    if (cancel) expect(window.scrollTo).not.toHaveBeenCalled();
    else expect(window.scrollTo).toHaveBeenLastCalledWith(0, 420);
    history.replaceState(null, "", location.pathname);
  },
);

it("tracks selection restoration from the focused control and yields to a newer focus", () => {
  render(
    <>
      <button>Selected record</button>
      <input aria-label="Newer draft" />
    </>,
  );
  screen.getByRole("button", { name: "Selected record" }).focus();
  const cancel = vi.fn();
  const intent = trackReturnIntent(cancel, { includeCurrentFocus: true });
  expect(intent.isCurrent()).toBe(true);
  screen.getByRole("textbox", { name: "Newer draft" }).focus();
  expect(intent.isCurrent()).toBe(false);
  expect(cancel).toHaveBeenCalledTimes(1);
  intent.dispose();
});
