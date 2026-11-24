// @vitest-environment jsdom
import React, { useState } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  cleanup,
  fireEvent,
  render,
  screen,
  waitFor,
} from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import axe from "axe-core";
import { Catalogue, type CatalogueRoute } from "../src/Catalogue";
import { AuthorGroups } from "../src/AuthorGroups";
import {
  catalogueComparisonTarget,
  decodeCatalogueAuthors,
  type AuthorEvidence,
} from "../src/author-groups-api";

const snapshot = {
  version: "2026.10.25.1",
  sha256: "a".repeat(64),
  fixture: true,
};
const author = { id: "1", name: "Fixture Author", version: snapshot.version };
const evidence = (): AuthorEvidence => ({
  schema_version: "librarium.author-groups.v1",
  snapshot,
  status: "available",
  truncated: false,
  groups: [
    {
      author,
      status: "complete",
      canonical_owners: 1,
      aliases: [{ name: "Fixture Pen Name", owners: 1 }],
      alias_count: 1,
      matched_aliases: [{ name: "Fixture Pen Name", owners: 1 }],
      matched_alias_count: 1,
    },
  ],
});
const work = {
  id: "w_fixture",
  title: "Fixture Volume",
  authors: [author],
  series: [],
  edition_count: 0,
};
const listing = () => ({
  snapshot,
  selected_author: null as typeof author | null,
  selected_series: null,
  works: [work],
  total: 1,
  page: 1,
  page_size: 24,
  author_evidence: evidence(),
});
const detail = () => ({
  ...work,
  snapshot,
  synopsis: null,
  ownership: "unconfirmed",
  editions: [],
  support: [],
  author_evidence: evidence(),
});
const json = (value: unknown, status = 200) =>
  new Response(JSON.stringify(value), { status });
let intercept: (url: URL) => Response | undefined;
let paths: URL[];
let navigations: Partial<CatalogueRoute>[];

function mount(initial: Partial<CatalogueRoute> = {}) {
  paths = [];
  navigations = [];
  vi.stubGlobal("matchMedia", () => ({ matches: false }));
  vi.spyOn(window, "scrollTo").mockImplementation(() => {});
  Element.prototype.scrollTo = vi.fn();
  const compareSource = vi.fn();
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      const url = new URL(input, location.origin);
      paths.push(url);
      const custom = intercept?.(url);
      if (custom) return custom;
      if (url.pathname === "/api/catalogue")
        return json({ status: "ready", total: 1, ...snapshot });
      if (url.pathname === "/api/catalogue/works/w_fixture")
        return json(detail());
      const value = listing();
      if (url.searchParams.get("author")) value.selected_author = author;
      return json(value);
    }),
  );
  function Harness() {
    const [route, setRoute] = useState<CatalogueRoute>({
      cq: "Fixture Pen Name",
      cp: 1,
      cw: "",
      cv: snapshot.version,
      ch: snapshot.sha256,
      cs: "",
      cb: "works",
      ca: "",
      ...initial,
    });
    return (
      <Catalogue
        route={route}
        compareSource={compareSource}
        navigate={(next) => {
          navigations.push(next);
          setRoute((current) => ({ ...current, ...next }));
        }}
      />
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
  return compareSource;
}
afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllGlobals();
  intercept = undefined!;
});

it("decodes exact groups but refuses mismatched snapshot, author, counts, duplicate and unknown fields", () => {
  expect(
    decodeCatalogueAuthors(listing(), snapshot, { page: 1 }).author_evidence,
  ).toEqual(evidence());
  const mutations: ((value: ReturnType<typeof listing>) => void)[] = [
    (v) => {
      v.author_evidence.snapshot = { ...snapshot, sha256: "b".repeat(64) };
    },
    (v) => {
      v.author_evidence.groups[0].author = {
        ...author,
        version: "2026.10.26.1",
      };
    },
    (v) => {
      v.author_evidence.groups[0].author = { ...author, id: "2" };
    },
    (v) => {
      v.author_evidence.groups[0].canonical_owners = 0;
    },
    (v) => {
      v.author_evidence.groups[0].aliases[0].owners = 0;
    },
    (v) => {
      v.author_evidence.groups[0].alias_count = 2;
    },
    (v) => {
      v.author_evidence.groups[0].matched_alias_count = 0;
    },
    (v) => {
      v.author_evidence.groups[0].matched_aliases[0].owners = 2;
    },
    (v) => {
      v.author_evidence.groups[0].aliases.push({
        ...v.author_evidence.groups[0].aliases[0],
      });
    },
    (v) => {
      v.author_evidence.groups.push({ ...v.author_evidence.groups[0] });
    },
    (v) => {
      v.author_evidence.status = "missing";
    },
    (v) => {
      v.author_evidence.truncated = true;
    },
    (v) => {
      Object.assign(v.author_evidence, { ready: true });
    },
    (v) => {
      v.page = 2;
    },
    (v) => {
      v.works.push({ ...work });
    },
    (v) => {
      v.author_evidence.groups[0].aliases[0].name = "Invalid\u0000credit";
      v.author_evidence.groups[0].matched_aliases[0].name =
        "Invalid\u0000credit";
    },
    (v) => {
      v.author_evidence.groups[0].aliases[0].name = "Invalid\ud800credit";
      v.author_evidence.groups[0].matched_aliases[0].name =
        "Invalid\ud800credit";
    },
  ];
  for (const mutate of mutations) {
    const value = structuredClone(listing());
    mutate(value);
    expect(() => decodeCatalogueAuthors(value, snapshot, { page: 1 })).toThrow(
      /unsupported author evidence/,
    );
  }
  const missingGroup = detail();
  missingGroup.author_evidence.groups = [];
  expect(() =>
    decodeCatalogueAuthors(missingGroup, snapshot, { work: work.id }),
  ).toThrow();
});

it("keeps missing, incompatible, invalid and legacy evidence distinct from complete groups", () => {
  for (const status of ["missing", "incompatible", "invalid"] as const) {
    const value = listing();
    value.author_evidence = { ...evidence(), status, groups: [] };
    expect(
      decodeCatalogueAuthors(value, snapshot, { page: 1 }).author_evidence
        ?.status,
    ).toBe(status);
    const view = render(<AuthorGroups evidence={value.author_evidence} />);
    expect(screen.getByText(/alias discovery is unavailable/)).toBeTruthy();
    view.unmount();
  }
  render(<AuthorGroups />);
  expect(screen.getByText(/were not supplied/)).toBeTruthy();
});

it("shows capped groups and globally ambiguous spellings without claiming agreement", () => {
  const value = evidence();
  const group = value.groups[0];
  group.aliases = Array.from({ length: 32 }, (_, index) => ({
    name: `Spelling ${index}`,
    owners: 2,
  }));
  group.alias_count = 33;
  group.status = "truncated";
  group.canonical_owners = 2;
  group.matched_aliases = [{ name: "Spelling 32", owners: 3 }];
  expect(
    decodeCatalogueAuthors({ ...detail(), author_evidence: value }, snapshot, {
      work: work.id,
    }),
  ).toBeTruthy();
  render(<AuthorGroups evidence={value} />);
  fireEvent.click(screen.getByText("Recorded author names"));
  expect(screen.getByText(/showing 32 of 33/)).toBeTruthy();
  expect(screen.getByText(/displayed group is incomplete/)).toBeTruthy();
  expect(screen.getByText(/canonical spelling is shared by 2/)).toBeTruthy();
  expect(screen.queryByText(/names agree/)).toBeNull();
});

it("discovers recorded spelling, retains alias query through author navigation, and passes exact work pins to source selection", async () => {
  const compare = mount();
  await screen.findByText("Fixture Pen Name", {
    selector: ".alias-search-matches span",
  });
  fireEvent.click(
    screen.getByRole("button", {
      name: /Select Fixture Volume|Fixture Volume/,
    }),
  );
  fireEvent.click(
    await screen.findByRole("button", { name: "Browse author Fixture Author" }),
  );
  await screen.findByRole("heading", { name: "Fixture Author", level: 1 });
  expect(navigations.at(-1)?.cq).toBe("Fixture Pen Name");
  const authorRequest = paths.find(
    (url) => url.searchParams.get("author") === "1",
  );
  expect(authorRequest?.searchParams.get("version")).toBe(snapshot.version);
  expect(authorRequest?.searchParams.get("sha256")).toBe(snapshot.sha256);
  fireEvent.click(
    screen.getByRole("button", {
      name: /Select Fixture Volume|Fixture Volume/,
    }),
  );
  fireEvent.click(
    await screen.findByRole("button", {
      name: "Compare with an inspected EPUB",
    }),
  );
  expect(compare).toHaveBeenCalledWith(
    work.id,
    snapshot.version,
    snapshot.sha256,
  );
  const result = await axe.run(document.body, {
    rules: { "color-contrast": { enabled: false } },
  });
  expect(result.violations).toEqual([]);
});

it("refuses malformed group responses and retries without losing the alias query", async () => {
  intercept = (url) => {
    if (url.pathname !== "/api/catalogue/works") return;
    const value = listing();
    value.author_evidence.groups[0].author = {
      ...author,
      version: "2026.10.26.1",
    };
    return json(value);
  };
  mount();
  await screen.findByRole("alert");
  expect(
    screen.queryByText("Fixture Pen Name", {
      selector: ".alias-search-matches span",
    }),
  ).toBeNull();
  intercept = undefined!;
  fireEvent.click(screen.getByRole("button", { name: "Retry catalogue" }));
  await screen.findByText("Fixture Pen Name", {
    selector: ".alias-search-matches span",
  });
  expect((screen.getByRole("searchbox") as HTMLInputElement).value).toBe(
    "Fixture Pen Name",
  );
});

it("uses explicit snapshot recovery and clears cross-version author IDs", async () => {
  intercept = (url) =>
    url.pathname === "/api/catalogue/works"
      ? json({ error: "Selected catalogue snapshot changed" }, 409)
      : undefined;
  mount({ ca: "1" });
  fireEvent.click(
    await screen.findByRole("button", { name: "Use current snapshot" }),
  );
  await waitFor(() =>
    expect(
      navigations.some(
        (next) =>
          next.ca === "" && next.cw === "" && next.cv === snapshot.version,
      ),
    ).toBe(true),
  );
});

it("requires a complete bounded work/version/digest comparison target", () => {
  expect(catalogueComparisonTarget()).toBeUndefined();
  expect(
    catalogueComparisonTarget(work.id, snapshot.version, snapshot.sha256),
  ).toEqual({
    work: work.id,
    version: snapshot.version,
    sha256: snapshot.sha256,
  });
  for (const parts of [
    [work.id, "", snapshot.sha256],
    ["../work", snapshot.version, snapshot.sha256],
    [work.id, snapshot.version, "x".repeat(64)],
    ["w".repeat(129), snapshot.version, snapshot.sha256],
  ])
    expect(catalogueComparisonTarget(...parts)).toBeNull();
});
