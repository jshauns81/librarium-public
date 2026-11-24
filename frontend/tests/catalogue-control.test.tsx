// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import {
  CatalogueControl,
  type CatalogueControlRoute,
} from "../src/CatalogueControl";

const pin = { version: "2026.10.24.2", sha256: "b".repeat(64), fixture: true };
const report = {
  snapshot: pin,
  producer: {
    status: "not_configured",
    message: "Reference ingestion is not configured.",
  },
  source_observations: [
    {
      source: "Fixture source",
      last_recorded_at: "2026-10-24",
      last_recorded_status: "completed",
      live: false,
    },
  ],
  counts: {
    incomplete: 25,
    conflicts: 3,
    possible_duplicates: 2,
    unmatched: null,
  },
  library_matching: {
    status: "not_assessed",
    message: "Library-wide matching has not run.",
  },
  queue: "incomplete",
  page: 1,
  pages: 2,
  page_size: 24,
  total: 25,
  works: [
    {
      id: "fixture-1",
      title: "Fixture: Glass Meridian",
      reasons: ["missing_author"],
    },
  ],
  scope: "Selected snapshot metadata only.",
};
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
let intercept: (url: string) => Response | Promise<Response> | undefined;
let calls: string[];
let navigate = vi.fn<(next: unknown, push?: boolean) => void>();
beforeEach(() => {
  calls = [];
  intercept = () => undefined;
  navigate = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      calls.push(url);
      const intercepted = intercept(url);
      if (intercepted) return intercepted;
      if (url === "/api/catalogue")
        return json({ status: "ready", ...pin, total: 40 });
      const params = new URL(url, "http://fixture").searchParams;
      return json({
        ...report,
        queue: params.get("queue"),
        page: Number(params.get("page")),
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});
function mount(initial: Partial<CatalogueControlRoute> = {}) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  function Harness() {
    const [route, setRoute] = useState({
      cv: "",
      ch: "",
      cc: "incomplete",
      ccp: 1,
      ...initial,
    });
    return (
      <CatalogueControl
        route={route}
        navigate={(next, push) => {
          navigate(next, push);
          setRoute((old) => ({ ...old, ...next }));
        }}
      />
    );
  }
  return render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
}
it("shows dated source observations and honest updater/unmatched gaps", async () => {
  const { container } = mount();
  expect(
    await screen.findByText("Reference ingestion is not configured."),
  ).toBeTruthy();
  expect(
    screen.getByText(/Unmatched library books: Not assessed/),
  ).toBeTruthy();
  expect(
    screen.getByText(/do not confirm that an updater is running/),
  ).toBeTruthy();
  const result = await axe.run(container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});
it("changes queues and pages under the exact snapshot and opens work evidence", async () => {
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Conflicting records 3" }),
  );
  await waitFor(() =>
    expect(
      calls.some(
        (url) =>
          url.includes("queue=conflicts") &&
          url.includes(`sha256=${pin.sha256}`) &&
          url.includes(`version=${pin.version}`),
      ),
    ).toBe(true),
  );
  fireEvent.click(await screen.findByRole("button", { name: "Next" }));
  await waitFor(() =>
    expect(calls.some((url) => url.includes("page=2"))).toBe(true),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Fixture: Glass Meridian" }),
  );
  expect(navigate).toHaveBeenLastCalledWith(
    expect.objectContaining({
      cm: "browse",
      cb: "works",
      cw: "fixture-1",
      cv: pin.version,
      ch: pin.sha256,
    }),
    true,
  );
});
it("keeps snapshot change explicit and retries failed control reads", async () => {
  intercept = (url) =>
    url.startsWith("/api/catalogue/control")
      ? json({ error: "Snapshot changed" }, 409)
      : undefined;
  mount({ cv: "2026.10.23.1", ch: "c".repeat(64) });
  expect(await screen.findByRole("alert")).toBeTruthy();
  expect(calls.some((url) => url.includes("version=2026.10.23.1"))).toBe(true);
  intercept = () => undefined;
  fireEvent.click(screen.getByRole("button", { name: "Use current snapshot" }));
  expect(
    await screen.findByText("Reference ingestion is not configured."),
  ).toBeTruthy();
});

it("shows the native import outcome without implying automatic fetching or switching the displayed pin", async () => {
  const latest = {
    version: "2026.10.28.1",
    sha256: "c".repeat(64),
    fixture: true,
  };
  intercept = (url) =>
    url.startsWith("/api/catalogue/control?")
      ? json({
          ...report,
          producer: {
            status: "manual",
            message:
              "Reference imports run on request. Automatic source fetching is not enabled.",
            current: latest,
            last_outcome: {
              request_key: "reference-request",
              completed_at: "2026-10-28T14:00:00Z",
              state: "succeeded",
              source: "blacklibrary",
              records: 5,
              version: latest.version,
              sha256: latest.sha256,
            },
          },
        })
      : undefined;
  mount({ cv: pin.version, ch: pin.sha256 });
  const outcome = await screen.findByRole("group", {
    name: "Last reference import",
  });
  expect(
    within(outcome).getByText("Completed", { selector: "dd" }),
  ).toBeTruthy();
  expect(within(outcome).getByText("blacklibrary")).toBeTruthy();
  expect(within(outcome).getByText("5")).toBeTruthy();
  expect(
    screen.getByText(/Automatic source fetching is not enabled/),
  ).toBeTruthy();
  expect(screen.getByText(/This view uses a different snapshot/)).toBeTruthy();
  expect(navigate).not.toHaveBeenCalled();
  fireEvent.click(
    screen.getByRole("button", { name: "Refresh update status" }),
  );
  await waitFor(() =>
    expect(
      calls.filter((url) => url.startsWith("/api/catalogue/control?")).length,
    ).toBeGreaterThan(1),
  );
  expect(
    vi.mocked(fetch).mock.calls.some(([, init]) => init?.method === "POST"),
  ).toBe(false);
});

it("keeps a preparing native import distinct from completed publication", async () => {
  intercept = (url) =>
    url.startsWith("/api/catalogue/control?")
      ? json({
          ...report,
          producer: {
            status: "manual",
            message: "Source evidence is being prepared.",
            current: null,
            last_outcome: {
              request_key: "reference-request",
              completed_at: null,
              state: "preparing",
              source: "lexicanum",
              records: 3,
              version: "2026.10.28.2",
              sha256: null,
            },
          },
        })
      : undefined;
  mount();
  const outcome = await screen.findByRole("group", {
    name: "Last reference import",
  });
  expect(
    within(outcome).getByText("Preparing", { selector: "dd" }),
  ).toBeTruthy();
  expect(within(outcome).getByText("Not recorded")).toBeTruthy();
});
