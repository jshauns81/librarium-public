// @vitest-environment jsdom
import React from "react";
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
  CatalogueHealth,
  ago,
  type HealthReport,
} from "../src/CatalogueHealth";

const missing = (reason: string) => ({
  state: "unavailable" as const,
  reason,
});
const pin = { version: "2026.10.25.1", sha256: "b".repeat(64), fixture: true };
const observed: HealthReport = {
  checked_at: "2026-11-04T10:00:00+00:00",
  headline: {
    level: "attention",
    reasons: ["1 harvest requests recorded errors in this snapshot's window."],
  },
  harvester: {
    state: "observed",
    live: missing("Live harvester status is not reported to Librarium yet."),
    last_recorded_at: "2026-10-25T09:30:00+00:00",
    last_recorded_age_seconds: 7200,
    window: {
      since: "2026-10-24T10:00:00+00:00",
      since_version: "2026.10.24.1",
    },
    sources: [
      {
        source: "lexicanum",
        asked: 1204,
        new_records: 17,
        errors: 1,
        last_at: "2026-10-25T09:30:00+00:00",
        last_status: "error",
      },
    ],
    tripped: missing("The cycle log is not reported to Librarium yet."),
    budget_deferred: missing("The cycle log is not reported to Librarium yet."),
  },
  changes: {
    state: "observed",
    from_version: "2026.10.24.1",
    to_version: "2026.10.25.1",
    added_count: 14,
    removed_count: 1,
    merged_count: 2,
    retitled_count: 1,
    added: [
      {
        id: "w-new",
        title: "Fixture: A Fresh Work",
        type: "novel",
        cover: {
          url: `/api/catalogue/covers/w-new/${"a".repeat(64)}?version=x`,
          sha256: "a".repeat(64),
          width: 600,
          height: 900,
          media_type: "image/jpeg",
        },
      },
      { id: "w-bare", title: "Fixture: No Art", type: null, cover: null },
    ],
    removed: [{ id: "w-gone", title: "Fixture: Gone", type: null }],
    retitled: [{ id: "w-renamed", from: "Old Name", to: "New Name" }],
  },
  size: {
    state: "observed",
    works: 3210,
    editions: 5402,
    authors: 410,
    series: 288,
    by_type: [
      { name: "novel", count: 2000 },
      { name: "short_story", count: 1210 },
    ],
    by_format: [{ name: "ebook", count: 5402 }],
    with_isbn: 2900,
    with_synopsis: 2500,
  },
  cycles: missing("The cycle log is not reported to Librarium yet."),
  covers: {
    state: "observed",
    saved: 2700,
    works_with_covers: 2650,
    awaiting: missing("The cover inbox is not reported to Librarium yet."),
    failed: missing("The cover inbox is not reported to Librarium yet."),
    last_download: missing("No download time is recorded in a snapshot."),
    upscale: {
      state: "observed",
      upscaled: 900,
      awaiting: 40,
      retry: 3,
      running: 1,
      failed: 2,
      paused: missing("The pause switch is not reported to Librarium yet."),
    },
  },
  controls: missing("Scan controls belong to BL Catalog's own status page."),
  librarium: {
    snapshot: {
      state: "observed",
      pinned: pin,
      dated: "2026-10-25",
      age_days: 10,
      latest_available: "2026.10.26.1",
      behind: true,
      stale: false,
      stale_after_days: 7,
      kept: ["2026.10.26.1", "2026.10.25.1"],
    },
    last_sync: missing(
      "Reference updates are not running inside Librarium yet.",
    ),
    jobs: {
      state: "observed",
      queued: 2,
      running: 1,
      expired_leases: 0,
      oldest_queued_age_seconds: 300,
      sample_incomplete: false,
      failed_last_day: 0,
      latest_failure: null,
    },
  },
  clients: [
    {
      id: "lexicanum_extension",
      name: "BLC Lexicanum Chrome extension",
      ...missing(
        "Not reported yet: this client sends Librarium no version or activity.",
      ),
    },
    {
      id: "cover_art_extension",
      name: "Library Finish Cover Art Chrome extension",
      ...missing(
        "Not reported yet: this client sends Librarium no version or activity.",
      ),
    },
    {
      id: "calibre_plugin",
      name: "BLC Calibre plugin",
      ...missing(
        "Not reported yet: this client sends Librarium no version or activity.",
      ),
    },
  ],
};
const unconfigured = "No catalogue snapshot is configured.";
const empty: HealthReport = {
  ...observed,
  headline: { level: "unavailable", reasons: [unconfigured] },
  harvester: missing(unconfigured),
  changes: missing(unconfigured),
  size: missing(unconfigured),
  covers: missing(unconfigured),
  librarium: {
    snapshot: missing(unconfigured),
    last_sync: missing(
      "Reference updates are not running inside Librarium yet.",
    ),
    jobs: missing("Librarium's job table could not be read."),
  },
};

let reply: () => Response | Promise<Response>;
const openWork = vi.fn();
const openOperations = vi.fn();
const json = (body: unknown, status = 200) =>
  new Response(JSON.stringify(body), { status });
beforeEach(() => {
  reply = () => json(observed);
  openWork.mockReset();
  openOperations.mockReset();
  vi.stubGlobal(
    "fetch",
    vi.fn(async () => reply()),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});

function mount(operations = true) {
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: 0 } },
  });
  return render(
    <QueryClientProvider client={client}>
      <CatalogueHealth
        openWork={openWork}
        openOperations={operations ? openOperations : undefined}
      />
    </QueryClientProvider>,
  );
}
const section = (name: string) => screen.getByRole("region", { name });

it("leads with one headline status and its reasons", async () => {
  mount();
  const status = await screen.findByText("Needs attention");
  const headline = status.closest(".health-headline") as HTMLElement;
  expect(headline.dataset.level).toBe("attention");
  expect(
    within(headline).getByText(/1 harvest requests recorded errors/),
  ).toBeTruthy();
  const order = [...document.querySelectorAll(".health-section h2")].map(
    (h) => h.textContent,
  );
  expect(order).toEqual([
    "BL Catalog status",
    "IHarvester",
    "IINew in this snapshot",
    "IIICatalogue size",
    "IVCycle history",
    "VCovers",
    "VIControls",
    "VIILibrarium",
    "VIIIClients",
  ]);
});

it("shows a loading state in every section before the report arrives", async () => {
  let finish: (r: Response) => void = () => {};
  reply = () => new Promise((resolve) => (finish = resolve));
  mount();
  expect(screen.getAllByText("Reading…").length).toBeGreaterThanOrEqual(9);
  finish(json(observed));
  await screen.findByText("Needs attention");
});

it("names the failure in every section and retries", async () => {
  reply = () => json({ error: "Catalogue snapshot is unavailable" }, 503);
  mount();
  const alert = await screen.findByRole("alert");
  expect(alert.textContent).toContain("could not be read");
  expect(
    screen.getAllByText("Not read: the health report could not be loaded.")
      .length,
  ).toBe(8);
  reply = () => json(observed);
  fireEvent.click(screen.getByRole("button", { name: "Retry health report" }));
  await screen.findByText("Needs attention");
});

it("harvester shows recorded sources, never inventing live state", async () => {
  mount();
  await screen.findByText("Needs attention");
  const harvester = section("Harvester");
  expect(
    within(harvester).getByText("Recorded since snapshot 2026.10.24.1"),
  ).toBeTruthy();
  const row = within(harvester).getByRole("row", { name: /Lexicanum/ });
  expect(row.textContent).toContain("1,204");
  expect(row.textContent).toContain("17");
  expect(within(harvester).getByText(/2 hours ago/)).toBeTruthy();
  expect(
    within(harvester).getAllByText(/not reported to Librarium yet/).length,
  ).toBe(3);
});

it("harvester empty and unavailable states", async () => {
  reply = () =>
    json({
      ...observed,
      harvester: { ...observed.harvester, sources: [], last_recorded_at: null },
    });
  mount();
  await screen.findByText("Needs attention");
  expect(
    within(section("Harvester")).getByText(
      "No harvest requests are recorded in this window.",
    ),
  ).toBeTruthy();
  cleanup();
  reply = () => json(empty);
  mount();
  await screen.findByText("Unavailable", { selector: ".health-level" });
  for (const name of [
    "Harvester",
    "New in this snapshot",
    "Catalogue size",
    "Covers",
  ])
    expect(within(section(name)).getByText(unconfigured)).toBeTruthy();
});

it("new works use real covers or a title page, and open in the books", async () => {
  mount();
  await screen.findByText("Needs attention");
  const changes = section("New in this snapshot");
  expect(within(changes).getByText("Added (first 2 of 14)")).toBeTruthy();
  const cover = changes.querySelector("img.book-cover") as HTMLImageElement;
  expect(cover.getAttribute("src")).toMatch(
    /^\/api\/catalogue\/covers\/w-new\//,
  );
  expect(changes.querySelector(".health-title-page")?.textContent).toBe(
    "Fixture: No Art",
  );
  fireEvent.click(
    within(changes).getByRole("button", { name: /A Fresh Work/ }),
  );
  expect(openWork).toHaveBeenCalledWith("w-new", pin);
  fireEvent.click(within(changes).getByRole("button", { name: "New Name" }));
  expect(openWork).toHaveBeenLastCalledWith("w-renamed", pin);
  expect(within(changes).getByText("Fixture: Gone")).toBeTruthy();
});

it("says plainly when a snapshot changed nothing", async () => {
  reply = () =>
    json({
      ...observed,
      changes: {
        ...observed.changes,
        added_count: 0,
        removed_count: 0,
        merged_count: 0,
        retitled_count: 0,
        added: [],
        removed: [],
        retitled: [],
      },
    });
  mount();
  await screen.findByText("Needs attention");
  expect(
    within(section("New in this snapshot")).getByText(
      "No works were added, removed, merged or retitled.",
    ),
  ).toBeTruthy();
});

it("catalogue size lists totals and breakdowns", async () => {
  mount();
  await screen.findByText("Needs attention");
  const size = section("Catalogue size");
  for (const value of ["3,210", "5,402", "410", "288", "2,900", "2,500"])
    expect(within(size).getAllByText(value).length).toBeGreaterThan(0);
  expect(within(size).getByText("short story")).toBeTruthy();
});

it("cycle history is unavailable with its reason", async () => {
  mount();
  await screen.findByText("Needs attention");
  expect(
    within(section("Cycle history")).getByText(
      "The cycle log is not reported to Librarium yet.",
    ),
  ).toBeTruthy();
});

it("covers and the upscale queue show counts and unavailable reasons", async () => {
  mount();
  await screen.findByText("Needs attention");
  const covers = section("Covers");
  for (const value of ["2,700", "2,650", "900", "40", "3", "2"])
    expect(within(covers).getAllByText(value).length).toBeGreaterThan(0);
  expect(
    within(covers).getByText(
      "The pause switch is not reported to Librarium yet.",
    ),
  ).toBeTruthy();
  expect(
    within(covers).getAllByText(
      "The cover inbox is not reported to Librarium yet.",
    ).length,
  ).toBe(2);
  reply = () =>
    json({
      ...observed,
      covers: { ...observed.covers, upscale: missing("No upscale queue.") },
    });
  cleanup();
  mount();
  await screen.findByText("Needs attention");
  expect(within(section("Covers")).getByText("No upscale queue.")).toBeTruthy();
});

it("controls explain why none are offered and keep operations reachable", async () => {
  mount();
  await screen.findByText("Needs attention");
  const controls = section("Controls");
  expect(
    within(controls).getByText(/BL Catalog's own status page/),
  ).toBeTruthy();
  fireEvent.click(
    within(controls).getByRole("button", { name: "the operations view" }),
  );
  expect(openOperations).toHaveBeenCalled();
  cleanup();
  mount(false);
  await screen.findByText("Needs attention");
  expect(within(section("Controls")).queryByRole("button")).toBeNull();
});

it("Librarium alerts when it serves an older snapshot and shows its jobs", async () => {
  mount();
  await screen.findByText("Needs attention");
  const librarium = section("Librarium");
  expect(within(librarium).getByRole("alert").textContent).toContain(
    "snapshot 2026.10.26.1 is saved, but Librarium still serves 2026.10.25.1",
  );
  expect(
    within(librarium).getByText("10 days (dated 2026-10-25)"),
  ).toBeTruthy();
  expect(
    within(librarium).getByText(
      "Reference updates are not running inside Librarium yet.",
    ),
  ).toBeTruthy();
  expect(
    within(librarium).getByText(/Oldest queued job waited 5 minutes/),
  ).toBeTruthy();
  expect(
    within(librarium).getByText(/No job failed in the last day/),
  ).toBeTruthy();
});

it("Librarium alerts when the served snapshot is stale", async () => {
  reply = () =>
    json({
      ...observed,
      librarium: {
        ...observed.librarium,
        snapshot: {
          ...observed.librarium.snapshot,
          behind: false,
          stale: true,
          age_days: 12,
        },
      },
    });
  mount();
  await screen.findByText("Needs attention");
  expect(within(section("Librarium")).getByRole("alert").textContent).toBe(
    "Stale: the served snapshot is 12 days old. Snapshots older than 7 days need attention.",
  );
});

it("harvest counts over all history say they do not drive the headline", async () => {
  reply = () =>
    json({
      ...observed,
      harvester: {
        ...observed.harvester,
        window: { since: null, since_version: null },
      },
    });
  mount();
  await screen.findByText("Needs attention");
  const harvester = section("Harvester");
  expect(
    within(harvester).getByText("Everything this snapshot recorded"),
  ).toBeTruthy();
  expect(
    within(harvester).getByText(/Their errors do not change the headline/),
  ).toBeTruthy();
  cleanup();
  reply = () => json(observed);
  mount();
  await screen.findByText("Needs attention");
  expect(
    within(section("Harvester")).queryByText(/do not change the headline/),
  ).toBeNull();
});

it("Librarium shows a completed sync and a recent failure", async () => {
  reply = () =>
    json({
      ...observed,
      librarium: {
        ...observed.librarium,
        snapshot: { ...observed.librarium.snapshot, behind: false },
        last_sync: {
          state: "observed",
          outcome: "succeeded",
          completed_at: "2026-10-25T08:00:00+00:00",
          version: "2026.10.25.1",
        },
        jobs: {
          ...observed.librarium.jobs,
          failed_last_day: 1,
          latest_failure: {
            kind: "epub_validation",
            at: "2026-11-04T09:00:00+00:00",
          },
        },
      },
    });
  mount();
  await screen.findByText("Needs attention");
  const librarium = section("Librarium");
  expect(within(librarium).queryByRole("alert")).toBeNull();
  expect(within(librarium).getByText(/Completed/)).toBeTruthy();
  expect(
    within(librarium).getByText(/Latest failure: epub validation/),
  ).toBeTruthy();
});

it("Librarium unavailable states keep their reasons", async () => {
  reply = () => json(empty);
  mount();
  await screen.findByText("Unavailable", { selector: ".health-level" });
  const librarium = section("Librarium");
  expect(within(librarium).getByText(unconfigured)).toBeTruthy();
  expect(
    within(librarium).getByText("Librarium's job table could not be read."),
  ).toBeTruthy();
});

it("clients say Not reported yet and carry no numbers", async () => {
  mount();
  await screen.findByText("Needs attention");
  const clients = section("Clients");
  expect(within(clients).getAllByText(/^Not reported yet/).length).toBe(3);
  expect(clients.textContent).not.toMatch(/\d/);
});

it("a healthy report keeps its scope in the reason", async () => {
  reply = () =>
    json({
      ...observed,
      headline: {
        level: "healthy",
        reasons: ["Nothing Librarium can see needs attention."],
      },
    });
  mount();
  const level = await screen.findByText("Sound");
  expect((level.closest(".health-headline") as HTMLElement).dataset.level).toBe(
    "healthy",
  );
});

it("has no axe violations", async () => {
  const view = mount();
  await screen.findByText("Needs attention");
  const result = await axe.run(view.container, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations.map((v) => v.id)).toEqual([]);
});

it("formats ages in whole units", () => {
  expect(ago(null)).toBe("time not recorded");
  expect(ago(30)).toBe("under a minute ago");
  expect(ago(60)).toBe("1 minute ago");
  expect(ago(7200)).toBe("2 hours ago");
  expect(ago(86400 * 3)).toBe("3 days ago");
});

it("refresh reads the report again", async () => {
  mount();
  await screen.findByText("Needs attention");
  const calls = (fetch as unknown as { mock: { calls: unknown[] } }).mock.calls
    .length;
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(
      (fetch as unknown as { mock: { calls: unknown[] } }).mock.calls.length,
    ).toBe(calls + 1),
  );
});

it("keeps the main view short with one closed Details disclosure", async () => {
  mount();
  await screen.findByText("Needs attention");
  const details = screen.getByText("Details", { selector: "summary" })
    .parentElement as HTMLDetailsElement;
  expect(details.open).toBe(false);
  expect(
    screen.getByRole("region", { name: "Catalogue size" }).closest("details")
      ?.open,
  ).toBe(false);
  expect(screen.getByRole("region", { name: "The week" })).toBeTruthy();
  fireEvent.click(screen.getByText("Details", { selector: "summary" }));
  expect(screen.getByRole("region", { name: "Catalogue size" })).toBeTruthy();
});

it("renders fresh, tripped, stale and unavailable telemetry honestly", async () => {
  const live = {
    state: "observed",
    fetched_at: "2026-11-10T12:00:00Z",
    age_seconds: 10,
    failure: "",
    status: {
      live: {
        state: "idle",
        paused: false,
        stalled: false,
        next_cycle_at: "2026-11-10T13:40:00Z",
      },
      cycles: [
        {
          started_at: "2026-11-10T11:00:00Z",
          harvest_new_records: 0,
          inbox_new_records: 0,
          stages: {},
          tripped: ["publisher"],
          tripped_reasons: { publisher: "API key rejected (401)" },
        },
      ],
    },
    covers: {
      upscale: {
        paused: false,
        state: "idle",
        completed: 3,
        queued: 1,
        failed: 0,
      },
    },
  };
  reply = () =>
    json({
      ...observed,
      telemetry: live,
      status_page_url: "https://catalogue.example.com/status",
    });
  mount();
  await screen.findByText(/The harvester is resting/);
  expect(screen.getByRole("note").textContent).toContain(
    "API key rejected (401)",
  );
  expect(
    screen
      .getByRole("link", { name: "Open BL Catalog status & controls" })
      .getAttribute("href"),
  ).toBe("https://catalogue.example.com/status");
  cleanup();
  reply = () =>
    json({
      ...observed,
      headline: { level: "stale", reasons: [] },
      telemetry: { ...live, state: "stale", age_seconds: 301 },
    });
  mount();
  await screen.findByText(/Last heard at/);
  expect(
    document.querySelector(".health-seal")?.getAttribute("data-seal"),
  ).toBe("muted");
  cleanup();
  reply = () =>
    json({
      ...empty,
      telemetry: { state: "unavailable", reason: "Not configured" },
    });
  mount();
  await screen.findByText(/live status is unavailable/);
  expect(
    screen.queryByRole("link", { name: "Open BL Catalog status & controls" }),
  ).toBeNull();
});

it("shows only qualified added plates and labels containing collections", async () => {
  reply = () =>
    json({
      ...observed,
      lately: {
        state: "observed",
        count: 14,
        plates: [
          {
            id: "w-new",
            title: "Fixture: A Fresh Work",
            cover:
              observed.changes.state === "observed"
                ? observed.changes.added[0].cover
                : null,
            collected_in: "Fixture Collection",
          },
        ],
      },
    });
  mount();
  await screen.findByText("14 works in the latest snapshot");
  const lately = screen.getByRole("region", { name: "Lately added" });
  expect(within(lately).getAllByRole("button").length).toBe(1);
  expect(
    within(lately).getByText("Collected in Fixture Collection"),
  ).toBeTruthy();
  expect(
    within(lately).getByText("14 works in the latest snapshot"),
  ).toBeTruthy();
  fireEvent.click(within(lately).getByRole("button"));
  expect(openWork).toHaveBeenCalledWith("w-new", pin);
});

it("uses a whole seal for sound evidence and local 12-hour times", async () => {
  const { healthSentence, clock } = await import("../src/CatalogueGlance");
  const telemetry = {
    state: "observed" as const,
    fetched_at: "2026-11-10T12:00:00Z",
    age_seconds: 0,
    failure: "",
    status: {
      live: {
        state: "idle",
        paused: false,
        stalled: false,
        next_cycle_at: "2026-11-10T13:40:00Z",
      },
      cycles: [],
    },
    covers: { upscale: {} },
  };
  expect(clock(telemetry.status.live.next_cycle_at)).toMatch(
    /\d{1,2}:40\s?[AP]M/,
  );
  expect(healthSentence(telemetry)).toContain(
    clock(telemetry.status.live.next_cycle_at),
  );
  expect(
    healthSentence({
      ...telemetry,
      status: {
        ...telemetry.status,
        live: { state: "harvest", phase: "publish" },
      },
    }),
  ).toContain("publishing a snapshot");
  expect(
    healthSentence({
      ...telemetry,
      status: { ...telemetry.status, live: { state: "idle", paused: true } },
    }),
  ).toContain("paused");
  reply = () =>
    json({
      ...observed,
      telemetry,
      headline: { level: "healthy", reasons: [] },
    });
  mount();
  await screen.findByText("Sound");
  expect(
    document.querySelector(".health-seal")?.getAttribute("data-seal"),
  ).toBe("whole");
  expect(screen.queryByRole("note")).toBeNull();
});

it("week marks distinguish records, quiet, failed and tripped cycles and keep selection", async () => {
  const cycle = {
    started_at: "2026-11-04T12:00:00Z",
    stages: {},
    tripped: [],
    harvest_new_records: 0,
  };
  reply = () =>
    json({
      ...observed,
      checked_at: "2026-11-04T18:00:00Z",
      telemetry: {
        state: "observed",
        fetched_at: "2026-11-04T18:00:00Z",
        age_seconds: 0,
        failure: "",
        status: {
          live: { state: "idle" },
          cycles: [
            cycle,
            {
              ...cycle,
              started_at: "2026-11-04T11:00:00Z",
              harvest_new_records: 3,
            },
            {
              ...cycle,
              started_at: "2026-11-04T10:00:00Z",
              stages: { harvest: { status: "error" } },
            },
            {
              ...cycle,
              started_at: "2026-11-04T09:00:00Z",
              tripped: ["publisher"],
            },
          ],
        },
        covers: { upscale: {} },
      },
    });
  mount();
  await screen.findByText("Needs attention");
  const week = screen.getByRole("region", { name: "The week" });
  expect(
    week.querySelectorAll('.health-cycle[data-filled="true"]').length,
  ).toBe(1);
  expect(
    week.querySelectorAll('.health-cycle[data-broken="true"]').length,
  ).toBe(1);
  expect(
    week.querySelectorAll('.health-cycle[data-ringed="true"]').length,
  ).toBe(1);
  const first = within(week).getAllByRole("button")[0];
  fireEvent.click(first);
  expect(first.getAttribute("aria-pressed")).toBe("true");
  fireEvent.click(screen.getByRole("button", { name: "Refresh" }));
  await waitFor(() =>
    expect(
      screen.getByRole("button", { name: "Refresh" }).getAttribute("aria-busy"),
    ).toBe("false"),
  );
  expect(first.getAttribute("aria-pressed")).toBe("true");
});

it("keeps non-source rubric causes and uses live cycles and budgets in Details", async () => {
  reply = () =>
    json({
      ...observed,
      headline: {
        level: "attention",
        reasons: [
          "Some sources need attention; the latest cycle ran with a tripped source.",
          "A stage failed in the latest cycle.",
        ],
      },
      telemetry: {
        state: "observed",
        fetched_at: observed.checked_at,
        age_seconds: 0,
        failure: "",
        status: {
          live: { state: "idle" },
          cycles: [
            {
              started_at: observed.checked_at,
              harvest_new_records: 17,
              tripped: ["isbngrid"],
              tripped_reasons: { isbngrid: "API key rejected (401)" },
              budget_deferred: { openlibrary: 12 },
              budget_spent: ["goodreads"],
            },
          ],
        },
        covers: {
          queued_images: 5,
          failed_uploads: 1,
          last_download_at: observed.checked_at,
          upscale: { paused: false },
        },
      },
    });
  mount();
  await screen.findByText("Needs attention");
  const headline = document.querySelector(".health-headline")!;
  expect(headline.textContent).toContain("A stage failed in the latest cycle.");
  expect(headline.textContent).not.toContain("tripped source");
  expect(screen.getByRole("note").textContent).toContain("ISBNgrid");
  expect(
    within(section("Cycle history")).queryByText(/not reported to Librarium/),
  ).toBeNull();
  expect(section("Cycle history").textContent).toContain("17");
  expect(section("Harvester").textContent).toContain("Budget deferrals");
  expect(section("Harvester").textContent).toContain("Open Library");
  expect(section("Harvester").textContent).toContain("12");
  expect(section("Harvester").textContent).toContain("Goodreads");
  const covers = section("Covers");
  expect(
    within(covers).getByText("Awaiting download").closest("div")?.textContent,
  ).toContain("Live report");
  expect(
    within(covers).getByText("Saved originals").closest("div")?.textContent,
  ).toContain("Served snapshot");
  expect(
    within(covers).getByText("Paused").closest("div")?.textContent,
  ).toContain("Live report");
});

it("labels stale cover figures with their age even without a snapshot", async () => {
  reply = () =>
    json({
      ...empty,
      telemetry: {
        state: "stale",
        fetched_at: observed.checked_at,
        age_seconds: 600,
        failure: "",
        status: { live: { state: "idle" }, cycles: [] },
        covers: { queued_images: 5, upscale: { paused: true } },
      },
    });
  mount();
  await screen.findByText("Unavailable", { selector: ".health-level" });
  expect(
    within(section("Covers")).getByText("Awaiting download").closest("div")
      ?.textContent,
  ).toContain("Last report · 10 minutes ago");
  expect(
    within(section("Covers")).getByText("Paused").closest("div")?.textContent,
  ).toContain("Last report · 10 minutes ago");
});
