// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, beforeEach, expect, it, vi } from "vitest";
import {
  act,
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
  within,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { FileInspections, type FileRoute } from "../src/FileInspections";
import type { Job } from "../src/types";

const pin = { version: "2026.10.24.2", sha256: "c".repeat(64), fixture: true };
const author = { id: "1", name: "Josh Reynolds" };
const row = { id: "w_one", title: "The Synthetic Volume", authors: [author] };
const otherRow = { ...row, id: "w_two", title: "Another Synthetic Volume" };
const job = (id = "job-a"): Job => ({
  id,
  kind: "epub",
  request_key: "request",
  work_id: "a".repeat(64),
  title: "Synthetic Volume.epub",
  state: "succeeded",
  revision: 4,
  checkpoint: 4,
  attempts: 1,
  message: "Report saved",
  updated_at: "2026-10-27T10:00:00Z",
  source_version: "librarium.epub-structure.v2",
  source_sha256: "a".repeat(64),
  input_fingerprint: "f".repeat(64),
  result: {
    report_sha256: "b".repeat(64),
    report_url: `/api/epub-inspections/${id}/report`,
    ready: false,
  },
});
const comparison = (id = "job-a", work = row) => ({
  schema_version: "librarium.package-comparison.v3",
  policy_version: "librarium.package-metadata.v3",
  job_id: id,
  source_sha256: "a".repeat(64),
  report_sha256: "b".repeat(64),
  catalogue: { ...pin, work_id: work.id, title: work.title, authors: [author] },
  title: { status: "same", epub: [work.title], catalogue: work.title },
  creators: {
    status: "same",
    epub: ["Joshua Reynolds"],
    catalogue: [author],
    matches: [
      {
        epub_name: "Joshua Reynolds",
        author_id: "1",
        catalogue_name: "Josh Reynolds",
        basis: "alias",
        status: "same",
      },
    ],
    missing_authors: [] as (typeof author)[],
  },
  isbn: {
    capture: "not_recorded",
    status: "unknown",
    entries: [] as {
      source: string;
      canonical_isbn13: string | null;
      status: string;
      basis: string | null;
      reason_codes: string[];
      source_position: {
        path: string;
        document_sha256: string;
        source_index: number;
      } | null;
      declarations: {
        kind: string;
        source_index: number;
        value: string;
        scheme: string | null;
        scheme_iri: string | null;
        refines: string | null;
        association: string;
      }[];
      editions: {
        edition_id: string;
        work_id: string | null;
        format: string | null;
        disputed: boolean;
      }[];
    }[],
    scope:
      "Only explicit urn:isbn: package identifiers are assessed against the selected catalogue snapshot. This is not proof of file authenticity or content identity.",
  },
  metadata_agrees: true,
  inspection_complete: true,
  ready: false,
  scope:
    "Package metadata only. Creator roles were not retained. This does not identify the work or establish ownership or readiness. The file and catalogue are unchanged.",
});
type Call = { url: URL; init: RequestInit };
let calls: Call[];
let workspaceSources: Map<string, Job>;
let client: QueryClient;
let intercept: (url: URL, init: RequestInit) => Promise<Response> | undefined;
const json = (value: unknown, status = 200) =>
  Promise.resolve(new Response(JSON.stringify(value), { status }));

beforeEach(() => {
  calls = [];
  workspaceSources = new Map();
  intercept = () => undefined;
  client = new QueryClient({
    defaultOptions: { queries: { retry: false, gcTime: Infinity } },
  });
  Element.prototype.scrollIntoView = vi.fn();
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  vi.stubGlobal(
    "fetch",
    vi.fn((input: string, init: RequestInit = {}) => {
      const url = new URL(input, location.origin);
      calls.push({ url, init });
      const custom = intercept(url, init);
      if (custom) return custom;
      if (url.pathname.endsWith("/workspace"))
        return json({
          schema_version: "librarium.book-workspace.v1",
          source: workspaceSources.get(url.pathname.split("/").at(-2)!),
          origin: null,
          selection: { fv: null, fa: null },
          jobs: [],
        });
      if (url.pathname === "/api/catalogue")
        return json({ status: "ready", total: 25, ...pin });
      if (url.pathname === "/api/catalogue/works")
        return json({
          snapshot: pin,
          works: [row, otherRow],
          total: 25,
          page: Number(url.searchParams.get("page") || 1),
          page_size: 24,
        });
      if (url.pathname.endsWith("/comparison"))
        return json(comparison(url.pathname.split("/").at(-2)));
      if (url.pathname === "/api/jobs/history")
        return json({ jobs: [], total: 0, page: 1, page_size: 24 });
      throw new Error(`Unexpected request ${url}`);
    }),
  );
});
afterEach(() => {
  cleanup();
  client.clear();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
});

function view(selected = job()) {
  workspaceSources.set(selected.id, selected);
  return (
    <QueryClientProvider client={client}>
      <FileInspections
        route={{ fj: selected.id, fq: "", fs: "", fp: 1 }}
        navigate={vi.fn()}
        session={{ csrf: "fixture", file_inspections: true }}
        sessionPending={false}
        sessionError={null}
        retrySession={vi.fn()}
        jobs={[selected]}
        merge={vi.fn()}
        cancel={vi.fn()}
        announceTerminal={vi.fn()}
        returnToReviews={vi.fn()}
        notify={vi.fn()}
      />
    </QueryClientProvider>
  );
}
async function open() {
  fireEvent.click(await screen.findByText("Compare with catalogue"));
  return await screen.findByLabelText("Search catalogue titles or authors");
}
async function search(query = "Synthetic") {
  const input = await open();
  fireEvent.change(input, { target: { value: query } });
  fireEvent.submit(input.closest("form")!);
  return await screen.findByRole("button", { name: `Compare ${row.title}` });
}
const comparisons = () =>
  calls.filter(({ url }) => url.pathname.endsWith("/comparison"));

it("requires explicit catalogue search and selection before comparing a completed inspection", async () => {
  render(view());
  expect(calls.some(({ url }) => url.pathname === "/api/catalogue")).toBe(
    false,
  );
  const choose = await search();
  expect(comparisons()).toHaveLength(0);
  fireEvent.click(choose);
  await screen.findByText("Recorded alias of Josh Reynolds");
  const request = comparisons()[0];
  expect(Object.fromEntries(request.url.searchParams)).toEqual({
    work: "w_one",
    version: pin.version,
    sha256: pin.sha256,
    source_sha256: "a".repeat(64),
    report_sha256: "b".repeat(64),
  });
  expect(request.init.method ?? "GET").toBe("GET");
  expect(screen.getAllByText("Joshua Reynolds").length).toBeGreaterThan(0);
  expect(screen.getByText(/creator roles were not retained/i)).toBeTruthy();
  expect(
    within(
      screen.getByRole("region", { name: "Package metadata comparison" }),
    ).getByText(/does not identify/i),
  ).toBeTruthy();
  expect(screen.queryByText(/^Ready$/)).toBeNull();
});

it("shows partial credits and missing coauthors without claiming full agreement", async () => {
  const value = comparison();
  value.creators.status = "partial";
  value.creators.missing_authors = [{ id: "2", name: "Another Author" }];
  value.metadata_agrees = false;
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText("Some creator names agree");
  expect(
    screen.getByText("Catalogue authors not covered: Another Author"),
  ).toBeTruthy();
  expect(
    screen.queryByText("The recorded title and creator names agree."),
  ).toBeNull();
});

it("preserves multiple titles and ambiguous creator evidence", async () => {
  const value = comparison();
  value.title = {
    status: "ambiguous",
    epub: ["First package title", "Second package title"],
    catalogue: row.title,
  };
  value.creators.status = "ambiguous";
  value.creators.matches[0] = {
    ...value.creators.matches[0],
    status: "ambiguous",
    basis: null,
    author_id: null,
    catalogue_name: null,
  } as never;
  value.metadata_agrees = false;
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText("More than one package title");
  expect(screen.getByText("First package title")).toBeTruthy();
  expect(screen.getByText("Second package title")).toBeTruthy();
  expect(screen.getByText("Creator names are ambiguous")).toBeTruthy();
});

it("explains unknown metadata when inspection did not finish", async () => {
  const value = comparison();
  value.inspection_complete = false;
  value.title.status = "unknown";
  value.creators.status = "unknown";
  value.creators.matches = [];
  value.metadata_agrees = false;
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText(
    /inspection stopped before reading the whole archive/i,
  );
  expect(screen.getByText("Title not compared")).toBeTruthy();
  expect(screen.getByText("Creator names not compared")).toBeTruthy();
});

it("keeps missing catalogue configuration explicit", async () => {
  intercept = (url) =>
    url.pathname === "/api/catalogue"
      ? json({ status: "not_configured" })
      : undefined;
  render(view());
  fireEvent.click(await screen.findByText("Compare with catalogue"));
  await screen.findByText(/catalogue is not configured/i);
  expect(comparisons()).toHaveLength(0);
});

it("requires an explicit snapshot switch after a pinned read is refused", async () => {
  let refused = true;
  intercept = (url) =>
    url.pathname === "/api/catalogue/works" && refused
      ? json({ error: "Snapshot unavailable" }, 409)
      : undefined;
  render(view());
  await search().catch(() => {});
  const recover = await screen.findByRole("button", {
    name: "Use current snapshot",
  });
  expect(
    calls.filter(({ url }) => url.pathname === "/api/catalogue"),
  ).toHaveLength(1);
  refused = false;
  fireEvent.click(recover);
  await waitFor(() =>
    expect(
      calls.filter(({ url }) => url.pathname === "/api/catalogue"),
    ).toHaveLength(2),
  );
  expect(comparisons()).toHaveLength(0);
});

it("rejects a comparison returned for another inspection or catalogue pin", async () => {
  const value = comparison("another-job");
  value.catalogue.sha256 = "d".repeat(64);
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText(
    /does not match this inspection and catalogue selection/i,
  );
  expect(screen.queryByText("Recorded alias of Josh Reynolds")).toBeNull();
});

it("abandons late comparisons when another catalogue work is selected", async () => {
  let resolve!: (value: Response) => void;
  intercept = (url) => {
    if (!url.pathname.endsWith("/comparison")) return undefined;
    if (url.searchParams.get("work") === "w_one")
      return new Promise((done) => {
        resolve = done;
      });
    return json(comparison("job-a", otherRow));
  };
  render(view());
  fireEvent.click(await search());
  fireEvent.click(
    await screen.findByRole("button", { name: `Compare ${otherRow.title}` }),
  );
  const result = await screen.findByRole("region", {
    name: "Package metadata comparison",
  });
  expect(
    within(result).getByRole("heading", { name: otherRow.title }),
  ).toBeTruthy();
  await act(async () => resolve(new Response(JSON.stringify(comparison()))));
  expect(within(result).queryByRole("heading", { name: row.title })).toBeNull();
  expect(comparisons()[0].init.signal?.aborted).toBe(true);
});

it("clears a comparison when the search intent changes and ignores its late response", async () => {
  let resolve!: (value: Response) => void;
  intercept = (url) =>
    url.pathname.endsWith("/comparison")
      ? new Promise((done) => {
          resolve = done;
        })
      : undefined;
  render(view());
  fireEvent.click(await search());
  fireEvent.change(
    screen.getByLabelText("Search catalogue titles or authors"),
    {
      target: { value: "Another" },
    },
  );
  await act(async () => resolve(new Response(JSON.stringify(comparison()))));
  expect(
    screen.queryByRole("region", { name: "Package metadata comparison" }),
  ).toBeNull();
  expect(
    screen.queryByRole("button", { name: `Compare ${row.title}` }),
  ).toBeNull();
});

it("abandons late comparison results when the selected file job changes", async () => {
  let resolve!: (value: Response) => void;
  intercept = (url) =>
    url.pathname.endsWith("/comparison")
      ? new Promise((done) => {
          resolve = done;
        })
      : undefined;
  const mounted = render(view());
  fireEvent.click(await search());
  mounted.rerender(view(job("job-b")));
  await act(async () => resolve(new Response(JSON.stringify(comparison()))));
  expect(
    screen.queryByRole("region", { name: "Package metadata comparison" }),
  ).toBeNull();
  expect(comparisons()[0].init.signal?.aborted).toBe(true);
});

it("lets failed comparisons retry the same selected source and work", async () => {
  let failed = true;
  intercept = (url) =>
    url.pathname.endsWith("/comparison") && failed
      ? json({ error: "Comparison unavailable" }, 503)
      : undefined;
  render(view());
  fireEvent.click(await search());
  const retry = await screen.findByRole("button", { name: "Retry comparison" });
  failed = false;
  retry.focus();
  fireEvent.click(retry);
  await screen.findByText("Recorded alias of Josh Reynolds");
  expect(comparisons()).toHaveLength(2);
  expect(comparisons()[0].url.search).toBe(comparisons()[1].url.search);
  await waitFor(() =>
    expect(
      screen
        .getByRole("region", { name: "Package metadata comparison" })
        .contains(document.activeElement),
    ).toBe(true),
  );
});

it("paginates pinned catalogue results and focuses the replacement summary", async () => {
  render(view());
  await search();
  const next = screen.getByRole("button", { name: "Next catalogue results" });
  next.focus();
  fireEvent.click(next);
  await waitFor(() =>
    expect(
      calls
        .filter(({ url }) => url.pathname === "/api/catalogue/works")
        .at(-1)!
        .url.searchParams.get("page"),
    ).toBe("2"),
  );
  await waitFor(() =>
    expect(document.activeElement?.textContent).toContain("Page 2"),
  );
  expect(comparisons()).toHaveLength(0);
});

it("keeps the focused pager available while the replacement page is pending", async () => {
  let resolve!: (value: Response) => void;
  intercept = (url) =>
    url.pathname === "/api/catalogue/works" &&
    url.searchParams.get("page") === "2"
      ? new Promise((done) => {
          resolve = done;
        })
      : undefined;
  render(view());
  await search();
  const next = screen.getByRole("button", { name: "Next catalogue results" });
  next.focus();
  fireEvent.click(next);
  expect(document.activeElement).toBe(next);
  expect(next.getAttribute("aria-disabled")).toBe("true");
  expect(
    (
      screen.getByRole("button", {
        name: `Compare ${row.title}`,
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  fireEvent.click(next);
  expect(
    calls.filter(({ url }) => url.pathname === "/api/catalogue/works"),
  ).toHaveLength(2);
  await act(async () =>
    resolve(
      new Response(
        JSON.stringify({
          snapshot: pin,
          works: [otherRow],
          total: 25,
          page: 2,
          page_size: 24,
        }),
      ),
    ),
  );
  await waitFor(() =>
    expect(document.activeElement?.textContent).toContain("Page 2"),
  );
});

it("focuses the committed comparison even when animation frames run before React commits", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  render(view());
  const compare = await search();
  compare.focus();
  fireEvent.click(compare);
  const result = await screen.findByRole("region", {
    name: "Package metadata comparison",
  });
  const heading = within(result).getByRole("heading", { name: row.title });
  await waitFor(() => expect(document.activeElement).toBe(heading));
});

it("keeps Retry focused while the comparison request is pending", async () => {
  let resolve!: (value: Response) => void;
  let retrying = false;
  intercept = (url) =>
    url.pathname.endsWith("/comparison")
      ? retrying
        ? new Promise((done) => {
            resolve = done;
          })
        : json({ error: "Comparison unavailable" }, 503)
      : undefined;
  render(view());
  fireEvent.click(await search());
  const retry = await screen.findByRole("button", { name: "Retry comparison" });
  retry.focus();
  retrying = true;
  fireEvent.click(retry);
  expect(document.activeElement).toBe(retry);
  expect(retry.getAttribute("aria-disabled")).toBe("true");
  await act(async () => resolve(new Response(JSON.stringify(comparison()))));
  await waitFor(() =>
    expect(
      screen
        .getByRole("region", { name: "Package metadata comparison" })
        .contains(document.activeElement),
    ).toBe(true),
  );
});

it("retains catalogue connection Retry focus and hands it to the ready search field", async () => {
  let resolve!: (value: Response) => void;
  let retrying = false;
  intercept = (url) =>
    url.pathname === "/api/catalogue"
      ? retrying
        ? new Promise((done) => {
            resolve = done;
          })
        : json({ error: "Catalogue offline" }, 503)
      : undefined;
  render(view());
  fireEvent.click(await screen.findByText("Compare with catalogue"));
  const retry = await screen.findByRole("button", {
    name: "Retry catalogue connection",
  });
  retry.focus();
  retrying = true;
  fireEvent.click(retry);
  expect(document.activeElement).toBe(retry);
  expect(retry.getAttribute("aria-disabled")).toBe("true");
  await act(async () =>
    resolve(
      new Response(JSON.stringify({ status: "ready", total: 25, ...pin })),
    ),
  );
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByLabelText("Search catalogue titles or authors"),
    ),
  );
});

it("retains snapshot recovery focus until the new pinned search is ready", async () => {
  let resolve!: (value: Response) => void;
  let switching = false;
  intercept = (url) => {
    if (url.pathname === "/api/catalogue" && switching)
      return new Promise((done) => {
        resolve = done;
      });
    if (url.pathname === "/api/catalogue/works")
      return json({ error: "Snapshot unavailable" }, 409);
    return undefined;
  };
  render(view());
  const input = await open();
  fireEvent.submit(input.closest("form")!);
  const recover = await screen.findByRole("button", {
    name: "Use current snapshot",
  });
  recover.focus();
  switching = true;
  fireEvent.click(recover);
  expect(document.activeElement).toBe(recover);
  expect(recover.getAttribute("aria-disabled")).toBe("true");
  expect(
    screen
      .getByRole("button", { name: "Search catalogue" })
      .getAttribute("aria-disabled"),
  ).toBe("true");
  await act(async () =>
    resolve(
      new Response(
        JSON.stringify({
          status: "ready",
          total: 25,
          ...pin,
          sha256: "d".repeat(64),
        }),
      ),
    ),
  );
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByLabelText("Search catalogue titles or authors"),
    ),
  );
  expect(
    screen.queryByRole("button", { name: "Use current snapshot" }),
  ).toBeNull();
});

it("provides labelled controls and comparison evidence without semantic axe violations", async () => {
  const value = comparison();
  const entry = isbnEntry("ambiguous");
  entry.editions[0].disputed = true;
  value.isbn = { ...value.isbn, status: "ambiguous", entries: [entry] };
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  const mounted = render(view());
  fireEvent.click(await search());
  await screen.findByText("Recorded alias of Josh Reynolds");
  fireEvent.click(screen.getByText("Matched catalogue editions (1)"));
  expect(
    (
      await axe.run(mounted.container, {
        rules: { "color-contrast": { enabled: false } },
      })
    ).violations,
  ).toEqual([]);
});

const isbnEntry = (status = "same") => ({
  source: "UrN:IsBn:0-306-40615-2",
  basis: "urn" as string | null,
  reason_codes: [] as string[],
  source_position: null as {
    path: string;
    document_sha256: string;
    source_index: number;
  } | null,
  declarations: [] as {
    kind: string;
    source_index: number;
    value: string;
    scheme: string | null;
    scheme_iri: string | null;
    refines: string | null;
    association: string;
  }[],
  canonical_isbn13: "9780306406157" as string | null,
  status,
  editions: [
    {
      edition_id: "edition-1",
      work_id: row.id as string | null,
      format: "ebook" as string | null,
      disputed: false,
    },
  ],
});

it("shows source ISBN10 and canonical ISBN13 evidence separately from title and creator agreement", async () => {
  const value = comparison();
  value.isbn = { ...value.isbn, status: "same", entries: [isbnEntry()] };
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  const section = await screen.findByRole("region", { name: "ISBN evidence" });
  expect(
    within(section).getByText("ISBN evidence agrees with the selected work"),
  ).toBeTruthy();
  expect(within(section).getByText("UrN:IsBn:0-306-40615-2")).toBeTruthy();
  expect(within(section).getByText("9780306406157")).toBeTruthy();
  expect(
    screen.getByText("The recorded title and creator names agree."),
  ).toBeTruthy();
  const disclosure = within(section).getByText(
    "Matched catalogue editions (1)",
  );
  fireEvent.click(disclosure);
  expect(within(section).getByText("edition-1")).toBeTruthy();
  expect(within(section).getByText("Selected work")).toBeTruthy();
  expect(within(section).getByText("ebook")).toBeTruthy();
  expect(
    within(section).getByText(
      /not proof of file authenticity or content identity/,
    ),
  ).toBeTruthy();
});

it.each([
  ["opf_scheme", 512, true],
  ["opf_scheme", 513, false],
  ["identifier_type", 257, false],
] as const)(
  "preserves the captured %s value bound at %i characters",
  async (kind, length, accepted) => {
    const value: any = comparison();
    const entry = isbnEntry("unsupported");
    entry.basis = null;
    entry.canonical_isbn13 = null;
    entry.editions = [];
    entry.source_position = {
      path: "EPUB/package.opf",
      document_sha256: "d".repeat(64),
      source_index: 3,
    };
    entry.declarations = [
      {
        kind,
        source_index: 3,
        value: "Z".repeat(length),
        scheme: null,
        scheme_iri: null,
        refines: null,
        association: "identifier",
      },
    ];
    value.isbn = {
      ...value.isbn,
      capture: "recorded",
      status: "unknown",
      entries: [entry],
    };
    intercept = (url) =>
      url.pathname.endsWith("/comparison") ? json(value) : undefined;
    render(view());
    fireEvent.click(await search());
    if (accepted) {
      await screen.findByRole("region", { name: "ISBN evidence" });
      fireEvent.click(screen.getByText("Identifier declarations (1)"));
      expect(screen.getByText("Z".repeat(length))).toBeTruthy();
    } else await screen.findByText(/invalid ISBN evidence/);
  },
);

it.each([
  ["scheme_iri", 556, true],
  ["scheme_iri", 1024, true],
  ["scheme_iri", 1025, false],
  ["scheme", 513, false],
] as const)(
  "keeps comparison results for bounded expanded IRIs: %s at %i characters",
  async (field, length, accepted) => {
    const value = comparison();
    const entry = isbnEntry("unsupported");
    entry.basis = null;
    entry.canonical_isbn13 = null;
    entry.editions = [];
    entry.reason_codes = ["unsupported_identifier_type_scheme"];
    entry.source_position = {
      path: "EPUB/package.opf",
      document_sha256: "d".repeat(64),
      source_index: 3,
    };
    const expanded = "http://www.editeur.org/ONIX/book/codelists/current.html#";
    const iri = expanded + "𝒳".repeat(length - expanded.length);
    entry.declarations = [
      {
        kind: "identifier_type",
        source_index: 4,
        value: "15",
        scheme: field === "scheme" ? "x".repeat(length) : "onix:codelist5",
        scheme_iri: field === "scheme_iri" ? iri : expanded + "codelist5",
        refines: "#book-id",
        association: "identifier",
      },
    ];
    value.isbn = {
      ...value.isbn,
      capture: "recorded",
      status: "unknown",
      entries: [entry],
    };
    intercept = (url) =>
      url.pathname.endsWith("/comparison") ? json(value) : undefined;
    const mounted = render(view());
    fireEvent.click(await search());
    if (accepted) {
      await screen.findByRole("region", { name: "ISBN evidence" });
      expect(
        screen.getByText("The recorded title and creator names agree."),
      ).toBeTruthy();
      expect(
        screen.getByText("The identifier type scheme is not supported."),
      ).toBeTruthy();
      fireEvent.click(screen.getByText("Identifier declarations (1)"));
      expect(screen.getByText(iri)).toBeTruthy();
      expect(
        (
          await axe.run(mounted.container, {
            rules: { "color-contrast": { enabled: false } },
          })
        ).violations,
      ).toEqual([]);
    } else {
      await screen.findByText(/invalid ISBN evidence/);
      expect(
        screen.queryByRole("region", { name: "ISBN evidence" }),
      ).toBeNull();
    }
  },
);

it.each([
  ["different", "ISBN evidence points to another work"],
  ["partial", "ISBN evidence partly agrees"],
  ["ambiguous", "ISBN evidence is ambiguous"],
  ["unknown", "ISBN evidence is unknown"],
])(
  "shows the %s ISBN disposition without changing name agreement",
  async (status, label) => {
    const value = comparison();
    value.isbn = {
      ...value.isbn,
      status,
      entries: [isbnEntry(status === "partial" ? "same" : status)],
    };
    intercept = (url) =>
      url.pathname.endsWith("/comparison") ? json(value) : undefined;
    render(view());
    fireEvent.click(await search());
    await screen.findByText(label);
    expect(
      screen.getByText("The recorded title and creator names agree."),
    ).toBeTruthy();
  },
);

it("keeps invalid, unsupported, disputed, other-work and unassigned evidence literal and escaped", async () => {
  const value = comparison();
  const ambiguous = isbnEntry("ambiguous");
  ambiguous.editions = [
    {
      edition_id: "<edition>&1",
      work_id: "other-work",
      format: "<format>",
      disputed: true,
    },
    {
      edition_id: "edition-unassigned",
      work_id: null,
      format: null,
      disputed: false,
    },
  ];
  value.isbn = {
    ...value.isbn,
    status: "ambiguous",
    entries: [
      ambiguous,
      {
        ...isbnEntry(),
        source: "urn:isbn:not-an-isbn",
        canonical_isbn13: null,
        status: "invalid",
        editions: [],
      },
      {
        ...isbnEntry(),
        source: "https://example.invalid/<identifier>" + "x".repeat(450),
        canonical_isbn13: null,
        status: "unsupported",
        editions: [],
      },
    ],
  };
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  const section = await screen.findByRole("region", { name: "ISBN evidence" });
  expect(within(section).getByText("Invalid declared ISBN")).toBeTruthy();
  expect(within(section).getByText("Unsupported identifier")).toBeTruthy();
  fireEvent.click(within(section).getByText("Matched catalogue editions (2)"));
  expect(within(section).getByText("Disputed")).toBeTruthy();
  expect(within(section).getByText("Other work")).toBeTruthy();
  expect(within(section).getByText("Work not assigned")).toBeTruthy();
  expect(within(section).getByText("<edition>&1")).toBeTruthy();
  expect(within(section).getByText("<format>")).toBeTruthy();
  expect(section.querySelector("a, img, format, edition")).toBeNull();
  expect(
    within(section).getByText(/Only explicit urn:isbn: package identifiers/),
  ).toBeTruthy();
});

it("shows an empty unknown ISBN assessment and incomplete inspection without claiming absence", async () => {
  const value = comparison();
  value.inspection_complete = false;
  value.metadata_agrees = false;
  value.title.status = "unknown";
  value.creators.status = "unknown";
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText("ISBN evidence is unknown");
  expect(
    screen.getByText(
      "No package identifiers were recorded for this assessment.",
    ),
  ).toBeTruthy();
  expect(
    screen.getByText(/inspection stopped before reading the whole archive/),
  ).toBeTruthy();
});

it.each([
  "missing",
  "null",
  "status",
  "scope",
  "entries",
  "source",
  "canonical",
  "entry status",
  "editions",
  "edition id",
  "work",
  "format",
  "disputed",
  "row limit",
  "edition limit",
  "combined limit",
  "field limit",
])("refuses malformed ISBN evidence: %s", async (field) => {
  const value: any = comparison();
  value.isbn.entries = [isbnEntry()];
  if (field === "missing") delete value.isbn;
  if (field === "null") value.isbn = null;
  if (field === "status") value.isbn.status = "toString";
  if (field === "scope") value.isbn.scope = false;
  if (field === "entries") value.isbn.entries = {};
  if (field === "source") value.isbn.entries[0].source = 123;
  if (field === "canonical")
    value.isbn.entries[0].canonical_isbn13 = "not-canonical";
  if (field === "entry status") value.isbn.entries[0].status = "partial";
  if (field === "editions") value.isbn.entries[0].editions = null;
  if (field === "edition id")
    value.isbn.entries[0].editions[0].edition_id = null;
  if (field === "work") value.isbn.entries[0].editions[0].work_id = 123;
  if (field === "format") value.isbn.entries[0].editions[0].format = [];
  if (field === "disputed")
    value.isbn.entries[0].editions[0].disputed = "false";
  if (field === "row limit")
    value.isbn.entries = Array.from({ length: 65 }, () => isbnEntry());
  if (field === "edition limit")
    value.isbn.entries[0].editions = Array(257).fill(isbnEntry().editions[0]);
  if (field === "combined limit")
    value.isbn.entries = Array.from({ length: 5 }, () => ({
      ...isbnEntry(),
      editions: Array(64).fill(isbnEntry().editions[0]),
    }));
  if (field === "field limit")
    value.isbn.entries[0].editions[0].format = "x".repeat(513);
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText(/invalid ISBN evidence/);
  expect(
    screen.queryByRole("region", { name: "Package metadata comparison" }),
  ).toBeNull();
  expect(screen.getByRole("button", { name: "Retry comparison" })).toBeTruthy();
});

it("admits the bounded maximum of identifier rows and edition references without shortening source fields", async () => {
  const value = comparison();
  const raw = "urn:isbn:" + "📚".repeat(503);
  value.isbn = {
    ...value.isbn,
    status: "ambiguous",
    entries: Array.from({ length: 64 }, () => ({
      ...isbnEntry("ambiguous"),
      source: raw,
      editions: Array.from({ length: 4 }, (_, i) => ({
        edition_id: `edition-${i}`,
        work_id: row.id,
        format: null,
        disputed: false,
      })),
    })),
  };
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  const evidence = await screen.findByRole("region", { name: "ISBN evidence" });
  expect(within(evidence).getAllByText(raw)).toHaveLength(64);
  expect(
    within(evidence).getAllByText("Matched catalogue editions (4)"),
  ).toHaveLength(64);
});

it.each([65, 256])(
  "admits %i edition references for one ISBN within the combined limit",
  async (count) => {
    const value = comparison();
    value.isbn.entries = [
      {
        ...isbnEntry(),
        editions: Array.from({ length: count }, (_, i) => ({
          edition_id: `edition-${i}`,
          work_id: row.id,
          format: "ebook",
          disputed: false,
        })),
      },
    ];
    intercept = (url) =>
      url.pathname.endsWith("/comparison") ? json(value) : undefined;
    render(view());
    fireEvent.click(await search());
    expect(
      await screen.findByText(`Matched catalogue editions (${count})`),
    ).toBeTruthy();
  },
);

it.each(["schema_version", "policy_version"])(
  "refuses a v1 %s instead of inventing absent ISBN evidence",
  async (field) => {
    const value = comparison();
    value[field as "schema_version" | "policy_version"] =
      field === "schema_version"
        ? "librarium.package-comparison.v1"
        : "librarium.package-metadata.v1";
    intercept = (url) =>
      url.pathname.endsWith("/comparison") ? json(value) : undefined;
    render(view());
    fireEvent.click(await search());
    await screen.findByText(
      /does not match this inspection and catalogue selection/,
    );
    expect(screen.queryByRole("region", { name: "ISBN evidence" })).toBeNull();
  },
);

it("shows captured ONIX basis, reasons and literal declarations beside independent ISBN evidence", async () => {
  const value = comparison();
  const entry = isbnEntry();
  entry.basis = "onix_isbn13";
  entry.reason_codes = ["future_source_reason"];
  entry.source_position = {
    path: "EPUB/package.opf",
    document_sha256: "d".repeat(64),
    source_index: 3,
  };
  entry.declarations = [
    {
      kind: "identifier_type",
      source_index: 4,
      value: "15",
      scheme: "onix:codelist5",
      scheme_iri:
        "http://www.editeur.org/ONIX/book/codelists/current.html#codelist5",
      refines: "#book-id",
      association: "identifier",
    },
  ];
  value.isbn = {
    ...value.isbn,
    capture: "recorded",
    status: "same",
    entries: [entry],
  };
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText("Basis: ONIX ISBN13 declaration");
  expect(
    screen.getByText(/Recorded reason: future_source_reason/),
  ).toBeTruthy();
  expect(
    screen.getByText("The recorded title and creator names agree."),
  ).toBeTruthy();
  fireEvent.click(screen.getByText("Identifier declarations (1)"));
  expect(screen.getByText("onix:codelist5")).toBeTruthy();
  expect(screen.getByText("#book-id")).toBeTruthy();
  expect(screen.getByText(/Package source index 3/)).toBeTruthy();
});

it.each([
  "capture",
  "basis",
  "reasons",
  "position",
  "declaration",
  "declaration limit",
])("refuses malformed v3 declaration evidence: %s", async (field) => {
  const value: any = comparison();
  value.isbn.capture = "recorded";
  value.isbn.entries = [isbnEntry()];
  const entry = value.isbn.entries[0];
  if (field === "capture") delete value.isbn.capture;
  if (field === "basis") entry.basis = "toString";
  if (field === "reasons") entry.reason_codes = [false];
  if (field === "position")
    entry.source_position = {
      path: "EPUB/package.opf",
      document_sha256: "bad",
      source_index: true,
    };
  if (field === "declaration")
    entry.declarations = [
      {
        kind: "identifier_type",
        source_index: 3,
        value: "15",
        scheme: null,
        scheme_iri: null,
        refines: null,
        association: "broken",
      },
    ];
  if (field === "declaration limit")
    entry.declarations = Array(257).fill({
      kind: "opf_scheme",
      source_index: 3,
      value: "ISBN",
      scheme: null,
      scheme_iri: null,
      refines: null,
      association: "identifier",
    });
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText(/invalid ISBN evidence/);
});

it("focuses the committed catalogue search field even when an animation frame fires before React commits", async () => {
  vi.stubGlobal("requestAnimationFrame", (callback: FrameRequestCallback) => {
    callback(0);
    return 1;
  });
  render(view());
  const reveal = await screen.findByText("Compare with catalogue");
  reveal.focus();
  fireEvent.click(reveal);
  const input = await screen.findByLabelText(
    "Search catalogue titles or authors",
  );
  await waitFor(() => expect(document.activeElement).toBe(input));
});

it("keeps nested identifier markup unsupported without calling the package conformance-invalid", async () => {
  const value = comparison();
  const entry = isbnEntry("unsupported");
  entry.basis = null;
  entry.canonical_isbn13 = null;
  entry.editions = [];
  entry.reason_codes = ["identifier_not_text"];
  value.isbn = { ...value.isbn, capture: "recorded", entries: [entry] };
  intercept = (url) =>
    url.pathname.endsWith("/comparison") ? json(value) : undefined;
  render(view());
  fireEvent.click(await search());
  await screen.findByText(
    "The identifier contains nested markup and was not assessed as plain ISBN text.",
  );
  expect(screen.getByText("Unsupported identifier")).toBeTruthy();
  expect(screen.queryByText("Invalid declared ISBN")).toBeNull();
  expect(
    screen.getByText("The recorded title and creator names agree."),
  ).toBeTruthy();
});

it.each(["corroborated", "conflicting", "ambiguous", "unconfirmed"])(
  "shows separate %s source attribution while whole-file identity remains unconfirmed",
  async (status) => {
    const value = comparison();
    const source_attribution = {
      schema_version: "librarium.source-attribution-comparison.v1",
      policy_version: "librarium.source-attribution-comparison.v1",
      observation_policy: "librarium.epub-source-attribution.v1",
      capture: "recorded",
      ready: false,
      status,
      job_id: value.job_id,
      source_sha256: value.source_sha256,
      report_sha256: value.report_sha256,
      catalogue: value.catalogue,
      observation_ids: ["source-title-1"],
      whole_file_identity: "unconfirmed",
      content_authentication: "unconfirmed",
    };
    intercept = (url) =>
      url.pathname.endsWith("/comparison")
        ? json({ ...value, source_attribution })
        : undefined;
    render(view());
    fireEvent.click(await search());
    expect(
      await screen.findByText(`Source attribution: ${status}`),
    ).toBeTruthy();
    expect(
      screen.getByText(/Whole-file identity remains unconfirmed/),
    ).toBeTruthy();
    expect(
      screen.getByText(/Source observations: source-title-1/),
    ).toBeTruthy();
  },
);
it.each([
  "source",
  "report",
  "work",
  "status",
  "whole_file",
  "policy",
  "observation_policy",
  "ready",
  "duplicate",
  "capture",
  "missing_observation",
])("refuses a mismatched attribution %s pin or claim", async (field) => {
  const value = comparison();
  const source_attribution = {
    schema_version: "librarium.source-attribution-comparison.v1",
    policy_version: "librarium.source-attribution-comparison.v1",
    observation_policy: "librarium.epub-source-attribution.v1",
    capture: "recorded",
    ready: false,
    status: "corroborated",
    job_id: value.job_id,
    source_sha256: value.source_sha256,
    report_sha256: value.report_sha256,
    catalogue: { ...value.catalogue },
    observation_ids: ["source-title-1"],
    whole_file_identity: "unconfirmed",
    content_authentication: "unconfirmed",
  };
  if (field === "capture") source_attribution.capture = "unconfirmed";
  if (field === "missing_observation") source_attribution.observation_ids = [];
  if (field === "policy") source_attribution.policy_version = "unknown";
  if (field === "observation_policy")
    source_attribution.observation_policy = "unknown";
  if (field === "ready") source_attribution.ready = true;
  if (field === "duplicate")
    source_attribution.observation_ids.push("source-title-1");
  if (field === "source") source_attribution.source_sha256 = "d".repeat(64);
  if (field === "report") source_attribution.report_sha256 = "d".repeat(64);
  if (field === "work") source_attribution.catalogue.work_id = "another";
  if (field === "status") source_attribution.status = "verified";
  if (field === "whole_file")
    source_attribution.whole_file_identity = "verified";
  intercept = (url) =>
    url.pathname.endsWith("/comparison")
      ? json({ ...value, source_attribution })
      : undefined;
  render(view());
  fireEvent.click(await search());
  expect(
    await screen.findByText(/source attribution does not match/),
  ).toBeTruthy();
  expect(screen.queryByText("Source attribution: corroborated")).toBeNull();
});
it("ends a comparison at the assessment with no review-copy route", async () => {
  intercept = (url) => {
    if (
      url.pathname.endsWith("/checks") ||
      url.pathname.startsWith("/api/library/") ||
      url.pathname.startsWith("/api/content-trust/")
    )
      return json({ error: "Not available in this fixture" }, 503);
  };
  render(view());
  fireEvent.click(await search());
  await screen.findByText("Recorded alias of Josh Reynolds");
  expect(
    screen.queryByRole("button", { name: /review copy|correction/i }),
  ).toBeNull();
  expect(screen.queryByRole("region", { name: /review copy/i })).toBeNull();
  expect(
    calls.some(({ url }) => /\/(preparation|corrections)$/.test(url.pathname)),
  ).toBe(false);
});

it("keeps the completed comparison when publishing its exact pin to the real route", async () => {
  const preserved = job();
  workspaceSources.set(preserved.id, preserved);
  function Harness() {
    const [route, setRoute] = useState<FileRoute>({
      fj: preserved.id,
      fq: "",
      fs: "",
      fp: 1,
    });
    return (
      <FileInspections
        route={route}
        navigate={(next) => setRoute((current) => ({ ...current, ...next }))}
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
    );
  }
  render(
    <QueryClientProvider client={client}>
      <Harness />
    </QueryClientProvider>,
  );
  fireEvent.click(await search("Synthetic"));
  await screen.findByText("Recorded alias of Josh Reynolds");
  await waitFor(() =>
    expect(
      calls.filter((call) => call.url.pathname.endsWith("/comparison")),
    ).toHaveLength(1),
  );
  expect(
    screen.getByRole("region", { name: "Package metadata comparison" }),
  ).toBeTruthy();
  expect(
    calls.some(
      (call) => call.url.pathname === `/api/catalogue/works/${row.id}`,
    ),
  ).toBe(false);
});
