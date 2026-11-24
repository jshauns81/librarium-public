// @vitest-environment jsdom
import React from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { CatalogueReview } from "../src/CatalogueReview";
import type { Job } from "../src/types";

let client: QueryClient;
let records: Job[];
let calls: { path: string; init: RequestInit }[];
let command: (init: RequestInit) => Promise<Response>;
let readJobs: (path: string) => Promise<Response>;
let readSession: () => Promise<Response>;
const digest = "a".repeat(64);
const reply = (body: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(body), { status }));
const record = (state = "queued", revision = 1): Job => ({
  id: "review-1",
  request_key: "key",
  kind: "catalogue",
  work_id: "w_one",
  title: "One",
  state,
  revision,
  checkpoint: state === "succeeded" ? 4 : 0,
  attempts: 1,
  message: "Saved catalogue metadata",
  updated_at: "2026-10-26T02:00:00Z",
  source_version: "v1",
  source_sha256: digest,
  input_fingerprint: "b".repeat(64),
  result:
    state === "succeeded"
      ? {
          findings: [
            {
              name: "ISBN checks",
              ok: false,
              status: "partial",
              detail: "200 of 300 editions checked.",
            },
          ],
          scope: "Catalogue metadata only.",
        }
      : {},
});
beforeEach(() => {
  localStorage.clear();
  records = [];
  calls = [];
  client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  command = () => reply(record(), 202);
  readJobs = () => reply({ jobs: records });
  readSession = () => reply({ csrf: "csrf-token" });
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const path = String(input);
      calls.push({ path, init });
      if (path === "/api/session") return readSession();
      if (path.startsWith("/api/jobs?")) return readJobs(path);
      if (init.method === "POST") return command(init);
      throw new Error(`Unexpected ${path}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function review(version = "v1", workId = "w_one", sha256 = digest) {
  return (
    <QueryClientProvider client={client}>
      <CatalogueReview
        workId={workId}
        title="One"
        version={version}
        sha256={sha256}
        fixture={false}
      />
    </QueryClientProvider>
  );
}
function open(version = "v1") {
  return render(review(version));
}
function deferred<T>() {
  let resolve!: (value: T) => void;
  let reject!: (error: Error) => void;
  const promise = new Promise<T>((yes, no) => {
    resolve = yes;
    reject = no;
  });
  return { promise, resolve, reject };
}
async function ready() {
  const button = (await screen.findByRole("button", {
    name: "Review catalogue metadata",
  })) as HTMLButtonElement;
  await waitFor(() => expect(button.disabled).toBe(false));
  return button;
}
async function refresh() {
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh review progress" }),
  );
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Refreshing…" })).toBeNull(),
  );
}
it("enqueues an exact pinned catalogue review with CSRF and a durable request key", async () => {
  open();
  const button = await screen.findByRole("button", {
    name: "Review catalogue metadata",
  });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByText("Saved catalogue metadata");
  const sent = calls.find(
    (c) => c.path === "/api/jobs" && c.init.method === "POST",
  )!;
  expect(JSON.parse(sent.init.body as string)).toEqual({
    catalogue_work_id: "w_one",
    version: "v1",
    sha256: digest,
  });
  expect(sent.init.headers).toMatchObject({
    "X-CSRFToken": "csrf-token",
    "Idempotency-Key": expect.any(String),
  });
  expect(
    (
      screen.getByRole("button", {
        name: "Review catalogue metadata",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.getByText("Metadata only. Books unchanged.")).toBeTruthy();
});
it("retries an unconfirmed request with the same key", async () => {
  let count = 0;
  command = () =>
    ++count === 1
      ? Promise.reject(new Error("Connection lost"))
      : reply(record(), 202);
  open();
  const button = await screen.findByRole("button", {
    name: "Review catalogue metadata",
  });
  await waitFor(() =>
    expect((button as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(button);
  await screen.findByText(/Review unconfirmed/);
  fireEvent.click(button);
  await screen.findByText("Saved catalogue metadata");
  const posts = calls.filter(
    (c) => c.path === "/api/jobs" && c.init.method === "POST",
  );
  expect(posts).toHaveLength(2);
  expect(posts[0].init.headers).toEqual(posts[1].init.headers);
});
it("shows saved partial findings and the original pin independently of the current snapshot", async () => {
  records = [record("succeeded", 5)];
  open("v2");
  await screen.findByText("Partial · ISBN checks");
  expect(screen.getByText("200 of 300 editions checked.")).toBeTruthy();
  expect(screen.getByText(/Saved review uses snapshot v1/)).toBeTruthy();
  expect(
    screen.getByRole("button", { name: "Review catalogue metadata" }),
  ).toBeTruthy();
});
it("shows the failure reason without opening a record and offers a new pinned retry", async () => {
  records = [
    {
      ...record("failed", 4),
      message: "Review interrupted. Retry when ready.",
    },
  ];
  command = (init) =>
    reply(
      {
        ...record(),
        id: "review-2",
        request_key: (init.headers as Record<string, string>)[
          "Idempotency-Key"
        ],
      },
      202,
    );
  open();
  const progress = await screen.findByRole("status", {
    name: "Review progress for One",
  });
  expect(progress.textContent).toContain(
    "Review interrupted. Retry when ready.",
  );
  expect(progress.closest("details")).toBeNull();
  const retry = screen.getByRole("button", { name: "Retry catalogue review" });
  await waitFor(() =>
    expect((retry as HTMLButtonElement).disabled).toBe(false),
  );
  fireEvent.click(retry);
  await screen.findByText("Review saved.");
  await screen.findByText("Queued");
  expect(screen.queryByText("Failed")).toBeNull();
  const sent = calls.find(
    (call) => call.path === "/api/jobs" && call.init.method === "POST",
  )!;
  expect(JSON.parse(sent.init.body as string)).toEqual({
    catalogue_work_id: "w_one",
    version: "v1",
    sha256: digest,
  });
  expect(
    (sent.init.headers as Record<string, string>)["Idempotency-Key"],
  ).not.toBe("key");
});
it("keeps a failed historical review distinct from reviewing the selected snapshot", async () => {
  records = [
    { ...record("failed", 4), message: "Earlier review interrupted." },
  ];
  open("v2");
  const reason = await screen.findByText("Earlier review interrupted.", {
    selector: "p",
  });
  expect(reason.closest("details")).toBeNull();
  expect(screen.getByText("Saved review uses snapshot v1.")).toBeTruthy();
  expect(
    screen.queryByRole("button", { name: "Retry catalogue review" }),
  ).toBeNull();
  expect(await ready()).toBeTruthy();
});
it("keeps cancellation unconfirmed after transport failure and accepts only the server result", async () => {
  records = [record("running", 2)];
  command = () => Promise.reject(new Error("offline"));
  open();
  fireEvent.click(await screen.findByRole("button", { name: "Cancel review" }));
  await screen.findByText(/Cancellation unconfirmed/);
  expect(screen.getByText("Reviewing")).toBeTruthy();
  command = () => reply(record("cancelled", 3));
  fireEvent.click(screen.getByRole("button", { name: "Cancel review" }));
  await screen.findByText("Cancelled");
});

it.each(["succeeded", "cancelled"])(
  "does not let a delayed GET regress a confirmed %s command",
  async (state) => {
    records = [record("running", 2)];
    const stale = deferred<Response>();
    open();
    await screen.findByText("Reviewing");
    readJobs = () => stale.promise;
    fireEvent.click(
      screen.getByRole("button", { name: "Refresh review progress" }),
    );
    await waitFor(() =>
      expect(
        (
          screen.getByRole("button", {
            name: "Refresh review progress",
          }) as HTMLButtonElement
        ).disabled,
      ).toBe(true),
    );
    command = () => reply(record(state, 4));
    fireEvent.click(screen.getByRole("button", { name: "Cancel review" }));
    await screen.findByText(state === "succeeded" ? "Complete" : "Cancelled");
    await act(async () => {
      stale.resolve(await reply({ jobs: [record("running", 2)] }));
    });
    await screen.findByRole("button", { name: "Refresh review progress" });
    expect(screen.queryByText("Reviewing")).toBeNull();
    expect(
      screen.getByText(state === "succeeded" ? "Complete" : "Cancelled"),
    ).toBeTruthy();
    expect(
      client.getQueryData<{ jobs: Job[] }>(["catalogue-reviews", "w_one"])
        ?.jobs[0].revision,
    ).toBe(4);
  },
);

it.each(["success", "failure"])(
  "isolates a late enqueue %s after selecting another work",
  async (outcome) => {
    const pending = deferred<Response>();
    command = () => pending.promise;
    readJobs = (path) =>
      reply({
        jobs: path.includes("w_two")
          ? [
              {
                ...record("succeeded", 5),
                id: "review-2",
                work_id: "w_two",
                message: "Second work saved result",
              },
            ]
          : [],
      });
    const view = open();
    fireEvent.click(await ready());
    await screen.findByRole("button", { name: "Saving review…" });
    view.rerender(review("v1", "w_two"));
    await screen.findByText("Second work saved result");
    await act(async () => {
      if (outcome === "success") pending.resolve(await reply(record(), 202));
      else pending.reject(new Error("late lost response"));
    });
    expect(screen.getByText("Second work saved result")).toBeTruthy();
    expect(screen.getByRole("status", { name: "" }).textContent).toBe("");
    expect(screen.queryByText("Saved catalogue metadata")).toBeNull();
    expect(
      client
        .getQueryData<{ jobs: Job[] }>(["catalogue-reviews", "w_two"])
        ?.jobs.map((job) => job.work_id),
    ).toEqual(["w_two"]);
  },
);

it("does not announce an old snapshot command after the selected pin changes", async () => {
  const pending = deferred<Response>();
  command = () => pending.promise;
  const view = open();
  fireEvent.click(await ready());
  await screen.findByRole("button", { name: "Saving review…" });
  view.rerender(review("v2", "w_one", "c".repeat(64)));
  await act(async () => {
    pending.resolve(await reply(record(), 202));
  });
  await screen.findByText(/Saved review uses snapshot v1/);
  expect(screen.getByRole("status", { name: "" }).textContent).toBe("");
  expect(
    (
      screen.getByRole("button", {
        name: "Review catalogue metadata",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
});

it("reconciles a lost POST response through saved progress and rotates the next intent", async () => {
  command = () => Promise.reject(new Error("reply lost"));
  open();
  fireEvent.click(await ready());
  await screen.findByText(/Review unconfirmed/);
  const first = calls.find((call) => call.init.method === "POST")!;
  const key = (first.init.headers as Record<string, string>)["Idempotency-Key"];
  expect(
    localStorage.getItem(`librarium-intent:catalogue:w_one:v1:${digest}`),
  ).toBe(key);
  records = [{ ...record("succeeded", 5), request_key: key }];
  await refresh();
  await screen.findByText("Review confirmed.");
  expect(
    localStorage.getItem(`librarium-intent:catalogue:w_one:v1:${digest}`),
  ).toBeNull();
  command = (init) =>
    reply(
      {
        ...record(),
        id: "review-new",
        request_key: (init.headers as Record<string, string>)[
          "Idempotency-Key"
        ],
      },
      202,
    );
  fireEvent.click(await ready());
  await screen.findByText("Review saved.");
  const posts = calls.filter((call) => call.init.method === "POST");
  expect(
    (posts[1].init.headers as Record<string, string>)["Idempotency-Key"],
  ).not.toBe(key);
});

it("reuses an unconfirmed intent only for its exact work and snapshot pin", async () => {
  command = () => Promise.reject(new Error("offline"));
  const view = open();
  fireEvent.click(await ready());
  await screen.findByText(/Review unconfirmed/);
  fireEvent.click(await ready());
  await waitFor(() =>
    expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(2),
  );
  await screen.findByText(/Review unconfirmed/);
  view.rerender(review("v2", "w_one", "c".repeat(64)));
  fireEvent.click(await ready());
  await waitFor(() =>
    expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(3),
  );
  const posts = calls.filter((call) => call.init.method === "POST");
  const keys = posts.map(
    (call) => (call.init.headers as Record<string, string>)["Idempotency-Key"],
  );
  expect(keys[0]).toBe(keys[1]);
  expect(keys[2]).not.toBe(keys[0]);
  expect(JSON.parse(posts[2].init.body as string)).toEqual({
    catalogue_work_id: "w_one",
    version: "v2",
    sha256: "c".repeat(64),
  });
});

it("does not steal focus from a control chosen while a command is pending", async () => {
  const pending = deferred<Response>();
  command = () => pending.promise;
  open();
  const button = await ready();
  button.focus();
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Saving review…" });
  const refreshButton = screen.getByRole("button", {
    name: "Refresh review progress",
  });
  refreshButton.focus();
  await act(async () => {
    pending.resolve(await reply(record(), 202));
  });
  await screen.findByText("Saved catalogue metadata");
  expect(document.activeElement).toBe(refreshButton);
});

it("does not restore command focus after navigating to another work", async () => {
  const pending = deferred<Response>();
  command = () => pending.promise;
  const view = open();
  const button = await ready();
  button.focus();
  fireEvent.click(button);
  await screen.findByRole("button", { name: "Saving review…" });
  view.rerender(review("v1", "w_two"));
  await ready();
  (document.activeElement as HTMLElement).blur();
  await act(async () => {
    pending.resolve(await reply(record(), 202));
  });
  expect(document.activeElement).toBe(document.body);
});

it("disables enqueue while the initial job read is unresolved", async () => {
  const pending = deferred<Response>();
  readJobs = () => pending.promise;
  open();
  const button = screen.getByRole("button", {
    name: "Review catalogue metadata",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(0);
  await act(async () => {
    pending.resolve(await reply({ jobs: [] }));
  });
  await ready();
});

it("requires session recovery before enqueue or cancelling an active job", async () => {
  readSession = () => reply({ error: "no session" }, 403);
  records = [record("running", 2)];
  open();
  await screen.findByText(/Review connection unavailable/);
  const enqueue = screen.getByRole("button", {
    name: "Review catalogue metadata",
  }) as HTMLButtonElement;
  const cancel = screen.getByRole("button", {
    name: "Cancel review",
  }) as HTMLButtonElement;
  expect(enqueue.disabled).toBe(true);
  expect(cancel.disabled).toBe(true);
  fireEvent.click(cancel);
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(0);
  readSession = () => reply({ csrf: "recovered-csrf" });
  fireEvent.click(
    screen.getByRole("button", { name: "Retry review connection" }),
  );
  await waitFor(() => expect(cancel.disabled).toBe(false));
  expect(enqueue.disabled).toBe(true);
});

it("blocks retrying an unconfirmed enqueue until a failed progress read recovers", async () => {
  open();
  const button = await ready();
  readJobs = () => reply({ error: "progress unavailable" }, 503);
  command = () => Promise.reject(new Error("lost response"));
  fireEvent.click(button);
  await screen.findByText(/Progress unavailable/);
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(1);
  readJobs = () => reply({ jobs: [] });
  await refresh();
  await ready();
});

it("filters unrelated recent jobs but respects an active job for this work on another pin", async () => {
  records = [
    {
      ...record("running", 3),
      id: "other-work",
      work_id: "w_other",
      message: "Other work private result",
      updated_at: "2026-10-27T00:00:00Z",
    },
    {
      ...record("running", 4),
      id: "synthetic",
      kind: "synthetic",
      message: "Unrelated synthetic inspection",
    },
    record("running", 2),
  ];
  open("v2");
  await screen.findByText("Reviewing");
  expect(screen.queryByText("Other work private result")).toBeNull();
  expect(screen.queryByText("Unrelated synthetic inspection")).toBeNull();
  expect(screen.getByText(/Saved review uses snapshot v1/)).toBeTruthy();
  expect(
    (
      screen.getByRole("button", {
        name: "Review catalogue metadata",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(
    new URL(
      calls.find((call) => call.path.startsWith("/api/jobs?"))!.path,
      "http://localhost",
    ).searchParams.get("work_id"),
  ).toBe("w_one");
});

it("preserves the saved fixture label, truncation and source binding under a real current pin", async () => {
  const saved = record("succeeded", 5);
  saved.result.synthetic = true;
  saved.result.findings![0].items = [
    {
      source: "fixture-publisher",
      native_id: "source-work-17",
      isbn: "invalid-isbn",
    },
  ];
  saved.result.findings![0].missing = ["publication year"];
  records = [saved];
  open("v2");
  await screen.findByText("Synthetic fixture review");
  expect(screen.getByText("Partial · ISBN checks")).toBeTruthy();
  expect(screen.getByText("200 of 300 editions checked.")).toBeTruthy();
  expect(screen.getByText(/Saved review uses snapshot v1/)).toBeTruthy();
  expect(screen.getByText("Finding details").closest("details")!.open).toBe(
    false,
  );
  fireEvent.click(screen.getByText("Finding details"));
  expect(screen.getByText("Finding details").closest("details")!.open).toBe(
    true,
  );
  expect(screen.getByText("Not recorded: publication year")).toBeTruthy();
  expect(screen.getByText("fixture-publisher")).toBeTruthy();
  expect(screen.getByText("source-work-17")).toBeTruthy();
  fireEvent.click(screen.getByText("Review record"));
  expect(screen.getByText(digest)).toBeTruthy();
  expect(screen.getByText(saved.input_fingerprint)).toBeTruthy();
  expect(screen.getByText("Catalogue metadata only.")).toBeTruthy();
});

it("keeps a polled confirmation authoritative when the original POST later loses its reply", async () => {
  const pending = deferred<Response>();
  command = () => pending.promise;
  open();
  fireEvent.click(await ready());
  await screen.findByRole("button", { name: "Saving review…" });
  const key = (
    calls.find((call) => call.init.method === "POST")!.init.headers as Record<
      string,
      string
    >
  )["Idempotency-Key"];
  records = [{ ...record("running", 2), request_key: key }];
  await refresh();
  await screen.findByText("Reviewing");
  await act(async () => {
    pending.reject(new Error("late lost reply"));
  });
  await waitFor(() =>
    expect(screen.queryByRole("button", { name: "Saving review…" })).toBeNull(),
  );
  expect(screen.queryByText(/Review unconfirmed/)).toBeNull();
  expect(screen.getByText("Reviewing")).toBeTruthy();
  expect(
    localStorage.getItem(`librarium-intent:catalogue:w_one:v1:${digest}`),
  ).toBeNull();
});

it("does not let a late cancellation overwrite another work's result or notice", async () => {
  records = [record("running", 2)];
  const pending = deferred<Response>();
  command = () => pending.promise;
  readJobs = (path) =>
    reply({
      jobs: path.includes("w_two")
        ? [
            {
              ...record("succeeded", 6),
              id: "review-two",
              work_id: "w_two",
              message: "Second result remains current",
            },
          ]
        : records,
    });
  const view = open();
  fireEvent.click(await screen.findByRole("button", { name: "Cancel review" }));
  await screen.findByRole("button", { name: "Cancelling…" });
  view.rerender(review("v2", "w_two", "d".repeat(64)));
  await screen.findByText("Second result remains current");
  await act(async () => {
    pending.resolve(await reply(record("cancelled", 3)));
  });
  expect(screen.getByText("Second result remains current")).toBeTruthy();
  expect(screen.queryByText("Cancelled")).toBeNull();
  expect(screen.getByRole("status", { name: "" }).textContent).toBe("");
  expect(
    client.getQueryData<{ jobs: Job[] }>(["catalogue-reviews", "w_two"])
      ?.jobs[0].state,
  ).toBe("succeeded");
});

it("does not replay the previous completed request after a confirmed POST", async () => {
  command = (init) =>
    reply({
      ...record("succeeded", 5),
      request_key: (init.headers as Record<string, string>)["Idempotency-Key"],
    });
  open();
  fireEvent.click(await ready());
  await screen.findByText("Saved review available.");
  const first = calls.find((call) => call.init.method === "POST")!;
  const firstKey = (first.init.headers as Record<string, string>)[
    "Idempotency-Key"
  ];
  expect(
    localStorage.getItem(`librarium-intent:catalogue:w_one:v1:${digest}`),
  ).toBeNull();
  command = (init) =>
    reply(
      {
        ...record(),
        id: "next-review",
        request_key: (init.headers as Record<string, string>)[
          "Idempotency-Key"
        ],
      },
      202,
    );
  fireEvent.click(await ready());
  await screen.findByText("Queued");
  const posts = calls.filter((call) => call.init.method === "POST");
  expect(posts).toHaveLength(2);
  expect(
    (posts[1].init.headers as Record<string, string>)["Idempotency-Key"],
  ).not.toBe(firstKey);
});

it("does not let polling another work confirm this work's unacknowledged request", async () => {
  command = () => Promise.reject(new Error("reply lost"));
  open();
  fireEvent.click(await ready());
  await screen.findByText(/Review unconfirmed/);
  const key = (
    calls.find((call) => call.init.method === "POST")!.init.headers as Record<
      string,
      string
    >
  )["Idempotency-Key"];
  records = [
    {
      ...record("succeeded", 9),
      work_id: "w_other",
      request_key: key,
      message: "Wrong target result",
    },
  ];
  await refresh();
  expect(screen.queryByText("Wrong target result")).toBeNull();
  expect(screen.getByText(/Review unconfirmed/)).toBeTruthy();
  expect(
    localStorage.getItem(`librarium-intent:catalogue:w_one:v1:${digest}`),
  ).toBe(key);
});

it("requires a successful initial progress read before accepting a review", async () => {
  readJobs = () => reply({ error: "not permitted" }, 403);
  open();
  await screen.findByText(/Progress unavailable/);
  const button = screen.getByRole("button", {
    name: "Review catalogue metadata",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(0);
  readJobs = () => reply({ jobs: [] });
  await refresh();
  await ready();
});

it("requires a working session even when progress is empty and ready", async () => {
  readSession = () => reply({ error: "session expired" }, 403);
  open();
  await screen.findByText(/Review connection unavailable/);
  await screen.findByRole("button", { name: "Refresh review progress" });
  const button = screen.getByRole("button", {
    name: "Review catalogue metadata",
  }) as HTMLButtonElement;
  expect(button.disabled).toBe(true);
  fireEvent.click(button);
  expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(0);
  readSession = () => reply({ csrf: "new-session-csrf" });
  fireEvent.click(
    screen.getByRole("button", { name: "Retry review connection" }),
  );
  fireEvent.click(await ready());
  await screen.findByText("Queued");
  expect(
    calls.find((call) => call.init.method === "POST")!.init.headers,
  ).toMatchObject({ "X-CSRFToken": "new-session-csrf" });
});

it("starts a distinct intent when only the snapshot digest changes", async () => {
  command = () => Promise.reject(new Error("not confirmed"));
  const view = open();
  fireEvent.click(await ready());
  await screen.findByText(/Review unconfirmed/);
  const previous = calls.find((call) => call.init.method === "POST")!;
  view.rerender(review("v1", "w_one", "e".repeat(64)));
  fireEvent.click(await ready());
  await waitFor(() =>
    expect(calls.filter((call) => call.init.method === "POST")).toHaveLength(2),
  );
  const next = calls.filter((call) => call.init.method === "POST")[1];
  expect(
    (next.init.headers as Record<string, string>)["Idempotency-Key"],
  ).not.toBe(
    (previous.init.headers as Record<string, string>)["Idempotency-Key"],
  );
  expect(JSON.parse(next.init.body as string)).toEqual({
    catalogue_work_id: "w_one",
    version: "v1",
    sha256: "e".repeat(64),
  });
});

it("keeps Refresh stable and usable while background polls update progress", async () => {
  open();
  await ready();
  const button = screen.getByRole("button", {
    name: "Refresh review progress",
  }) as HTMLButtonElement;
  button.focus();
  const pending = deferred<Response>();
  const before = calls.filter((call) =>
    call.path.startsWith("/api/jobs?"),
  ).length;
  readJobs = () => pending.promise;
  await waitFor(
    () =>
      expect(
        calls.filter((call) => call.path.startsWith("/api/jobs?")).length,
      ).toBeGreaterThan(before),
    { timeout: 2500 },
  );
  expect(button.textContent).toBe("Refresh");
  expect(button.disabled).toBe(false);
  expect(document.activeElement).toBe(button);
  pending.resolve(
    new Response(
      JSON.stringify({
        jobs: [{ ...record("running", 2), message: "Background checkpoint" }],
      }),
    ),
  );
  await screen.findByText("Background checkpoint");
  expect(button.textContent).toBe("Refresh");
});

it("shows manual refresh progress and re-enables the action after failure", async () => {
  open();
  await ready();
  const button = screen.getByRole("button", {
    name: "Refresh review progress",
  }) as HTMLButtonElement;
  const pending = deferred<Response>();
  readJobs = () => pending.promise;
  fireEvent.click(button);
  await waitFor(() => expect(button.textContent).toBe("Refreshing…"));
  expect(button.disabled).toBe(true);
  pending.resolve(
    new Response(JSON.stringify({ error: "Saved progress unavailable" }), {
      status: 503,
    }),
  );
  await waitFor(() => expect(button.disabled).toBe(false));
  expect(button.textContent).toBe("Refresh");
  expect(screen.getByText(/Progress unavailable/)).toBeTruthy();
});

it("does not let an old book refresh clear a newer book's refresh state", async () => {
  const mounted = open();
  await ready();
  const first = deferred<Response>();
  const second = deferred<Response>();
  readJobs = (path) =>
    path.includes("w_two") ? second.promise : first.promise;
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh review progress" }),
  );
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Refresh review progress" })
        .textContent,
    ).toBe("Refreshing…"),
  );
  mounted.rerender(review("v1", "w_two"));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Refresh review progress" })
        .textContent,
    ).toBe("Refresh"),
  );
  const button = screen.getByRole("button", {
    name: "Refresh review progress",
  }) as HTMLButtonElement;
  fireEvent.click(button);
  await waitFor(() => expect(button.textContent).toBe("Refreshing…"));
  await act(async () => {
    first.resolve(new Response(JSON.stringify({ jobs: [] })));
  });
  expect(button.textContent).toBe("Refreshing…");
  expect(button.disabled).toBe(true);
  second.resolve(new Response(JSON.stringify({ jobs: [] })));
  await waitFor(() => expect(button.disabled).toBe(false));
});
