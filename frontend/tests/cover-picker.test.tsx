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
import type { CoverEntry } from "../src/cover-review-api";
import { CoverPicker } from "../src/CoverPicker";
import { coverEntry } from "./cover-review-fixtures";

const entry = coverEntry(1) as CoverEntry;
const pin = { version: "2026.11.11.1", sha256: "a".repeat(64) };
function choice(n: number, label: string, selectable = true) {
  return {
    id: `00000000-0000-4000-8000-${String(n + 10).padStart(12, "0")}`,
    label,
    title: entry.title,
    sha256: "b".repeat(64),
    original_sha256: (n === 1 ? "c" : "b").repeat(64),
    width: n === 1 ? 1260 : 315,
    height: n === 1 ? 2032 : 508,
    method: n === 1 ? "stored_derivative" : "original",
    pipeline: n === 1 ? "realesrgan-x4plus-v1" : "",
    media_type: "image/jpeg",
    policy: "librarium.cover-choice.v1",
    source_name: "Lexicanum",
    source_url: null,
    source: "https://example.org/cover.jpg",
    work_id: "work-one",
    url: `/api/catalogue/covers/work-one/${"b".repeat(64)}?version=${pin.version}&sha256=${pin.sha256}${n === 1 ? "&variant=upscaled" : ""}`,
    selectable,
    meets_width_floor: n === 1,
    reason: selectable
      ? "Title and authors match one catalogue work. Confirm the edition visually."
      : "Different work or kind. Not selectable.",
  };
}
let data: ReturnType<typeof fixture>, writes: RequestInit[], failed: boolean;
function fixture() {
  return {
    entry_id: entry.id,
    revision: 1,
    library_uuid: entry.library_uuid,
    book_uuid: entry.book_uuid,
    inventory: "inventory",
    snapshot: pin,
    policy: "librarium.cover-choice.v1",
    web_sources_enabled: false,
    candidates: [
      choice(1, "Enhanced"),
      choice(2, "Original"),
      choice(3, "Original", false),
    ],
    default_candidate_id: choice(1, "Enhanced").id as string | null,
    selection: null as null | {
      id: string;
      candidate_id: string;
      status: string;
      reason: string;
    },
    source: { status: "complete", reason: "" },
  };
}
beforeEach(() => {
  data = fixture();
  writes = [];
  failed = false;
  HTMLDialogElement.prototype.showModal = function () {
    this.setAttribute("open", "");
  };
  HTMLDialogElement.prototype.close = function () {
    this.removeAttribute("open");
  };
  vi.stubGlobal(
    "fetch",
    vi.fn(async (_input: string, init: RequestInit = {}) => {
      if (init.method === "POST") {
        writes.push(init);
        if (failed)
          return new Response(
            JSON.stringify({
              code: "choice_changed",
              error: "The current cover changed. Refresh before trying again.",
            }),
            { status: 409 },
          );
        const body = JSON.parse(String(init.body));
        data.selection = {
          id: "00000000-0000-4000-8000-000000000099",
          candidate_id: body.candidate_id,
          status: "awaiting_approval",
          reason: "",
        };
      }
      return new Response(JSON.stringify(data), {
        status: init.method === "POST" ? 201 : 200,
      });
    }),
  );
});
afterEach(() => {
  cleanup();
  vi.unstubAllGlobals();
});
function mount() {
  const close = vi.fn();
  const saved = vi.fn();
  const client = new QueryClient({
    defaultOptions: { queries: { retry: false }, mutations: { retry: false } },
  });
  render(
    <QueryClientProvider client={client}>
      <CoverPicker
        entry={entry}
        inventory="inventory"
        pin={pin}
        csrf="synthetic-csrf"
        close={close}
        saved={saved}
      />
    </QueryClientProvider>,
  );
  return { close, saved, client };
}

it("compares missing current honestly and defaults to enhanced; digits select without saving", async () => {
  mount();
  const dialog = await screen.findByRole("dialog", { name: "Choose a cover" });
  expect(
    (
      await within(dialog).findByRole("button", { name: /1 Enhanced/ })
    ).getAttribute("aria-pressed"),
  ).toBe("true");
  expect(within(dialog).getByText("No current cover")).toBeTruthy();
  expect(
    within(dialog).queryByRole("button", { name: "Preview current" }),
  ).toBeNull();
  fireEvent.keyDown(dialog, { key: "2" });
  expect(
    within(dialog)
      .getByRole("button", { name: /2 Original/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.keyDown(dialog, { key: "3" });
  expect(writes).toHaveLength(0);
  expect(
    within(dialog).queryByRole("button", { name: /Apply|Upscale/ }),
  ).toBeNull();
  fireEvent.click(
    within(dialog).getByRole("button", { name: "Use this cover" }),
  );
  expect(
    await within(dialog).findByText("Selected; awaiting approval"),
  ).toBeTruthy();
  expect(writes).toHaveLength(1);
  expect(JSON.parse(String(writes[0].body)).candidate_id).toBe(
    data.candidates[1].id,
  );
  expect(
    within(dialog).queryByRole("button", { name: "Use this cover" }),
  ).toBeNull();
});
it("preview and evidence stay inside the dialog and Escape returns to comparison", async () => {
  mount();
  await screen.findByRole("button", { name: "Preview selected" });
  fireEvent.click(screen.getByRole("button", { name: "Preview selected" }));
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Back to comparison" }),
    ),
  );
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "Escape" });
  await waitFor(() =>
    expect(document.activeElement).toBe(
      screen.getByRole("button", { name: "Preview selected" }),
    ),
  );
  fireEvent.click(screen.getAllByText("Why this cover?")[0]);
  expect(screen.getAllByText(/Title and authors match/).length).toBeGreaterThan(
    0,
  );
  fireEvent.click(screen.getByText("Source & method"));
  expect(screen.getAllByText(/realesrgan-x4plus-v1/).length).toBeGreaterThan(0);
});
it("restores a saved original on reload and permits changing it without duplicating status", async () => {
  data.selection = {
    id: "00000000-0000-4000-8000-000000000099",
    candidate_id: data.candidates[1].id,
    status: "awaiting_approval",
    reason: "",
  };
  mount();
  expect(await screen.findByText("Selected; awaiting approval")).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: /2 Original/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "1" });
  expect(screen.getByRole("button", { name: "Use this cover" })).toBeTruthy();
});
it("retains the choice after a refusal and offers a real refresh", async () => {
  failed = true;
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Use this cover" }),
  );
  expect((await screen.findByRole("alert")).textContent).toContain(
    "current cover changed",
  );
  expect(screen.getByRole("button", { name: "Refresh choices" })).toBeTruthy();
  expect(screen.queryByText("Selected; awaiting approval")).toBeNull();
});
it("traps focus and scopes shortcuts to unmodified keys", async () => {
  mount();
  await screen.findByRole("button", { name: "Use this cover" });
  const dialog = screen.getByRole("dialog");
  const close = screen.getByRole("button", { name: "Close cover picker" });
  close.focus();
  fireEvent.keyDown(close, { key: "Tab", shiftKey: true });
  expect(document.activeElement).toBe(
    screen.getByRole("button", { name: "Use this cover" }),
  );
  fireEvent.keyDown(dialog, { key: "2", shiftKey: true });
  expect(
    screen
      .getByRole("button", { name: /1 Enhanced/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("does not offer a saved status for stale artwork and offers a fresh choice", async () => {
  data.selection = {
    id: "00000000-0000-4000-8000-000000000099",
    candidate_id: data.candidates[0].id,
    status: "stale",
    reason: "The catalogue artwork changed. Choose a cover again.",
  };
  mount();
  expect(await screen.findByText(/catalogue artwork changed/)).toBeTruthy();
  expect(screen.queryByText("Selected; awaiting approval")).toBeNull();
  expect(screen.getByRole("button", { name: "Use this cover" })).toBeTruthy();
});
it("explains an empty local source without a dead action", async () => {
  data.candidates = [];
  data.default_candidate_id = null;
  data.source = {
    status: "unavailable",
    reason: "The catalogue original could not be verified.",
  };
  mount();
  expect(
    await screen.findByText("The catalogue original could not be verified."),
  ).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Use this cover" })).toBeNull();
});
it("failed selected image cannot be submitted", async () => {
  mount();
  await screen.findByRole("button", { name: "Use this cover" });
  fireEvent.error(
    screen.getByAltText("Selected enhanced cover of The Lantern Atlas"),
  );
  expect(
    (
      screen.getByRole("button", {
        name: "Use this cover",
      }) as HTMLButtonElement
    ).disabled,
  ).toBe(true);
  expect(screen.queryByRole("button", { name: "Preview selected" })).toBeNull();
});

it("rejects choices that escape the pinned book, image, or derivative contract", async () => {
  const { decodeChoices } = await import("../src/cover-picker-api");
  const mutations: ((value: ReturnType<typeof fixture>) => void)[] = [
    (value) => {
      value.book_uuid = "other-book";
    },
    (value) => {
      value.inventory = "other-inventory";
    },
    (value) => {
      value.snapshot = { ...pin, sha256: "f".repeat(64) };
    },
    (value) => {
      value.candidates[0].url = "https://example.org/tracking.jpg";
    },
    (value) => {
      value.candidates[0].url = value.candidates[0].url.replace(
        "&variant=upscaled",
        "",
      );
    },
    (value) => {
      value.candidates[0].width = 999;
    },
    (value) => {
      value.candidates[1].original_sha256 = "f".repeat(64);
    },
    (value) => {
      value.candidates.push(value.candidates[0]);
    },
    (value) => {
      value.default_candidate_id = value.candidates[2].id;
    },
    (value) => {
      value.selection = {
        id: "00000000-0000-4000-8000-000000000099",
        candidate_id: value.candidates[2].id,
        status: "awaiting_approval",
        reason: "",
      };
    },
  ];
  for (const mutate of mutations) {
    const value = fixture();
    mutate(value);
    expect(() => decodeChoices(value, entry, "inventory", pin)).toThrow(
      /could not be verified/,
    );
  }
});

it("numbers only selectable choices and maps digit keys across blocked choices", async () => {
  data.candidates = [
    data.candidates[2],
    data.candidates[0],
    data.candidates[1],
  ];
  mount();
  const enhanced = await screen.findByRole("button", { name: /1 Enhanced/ });
  const blocked = screen.getByRole("button", { name: /Not selectable/ });
  expect(blocked.querySelector(".cover-picker-key")).toBeNull();
  expect(blocked.textContent).toContain(data.candidates[0].reason);
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "2" });
  expect(
    screen
      .getByRole("button", { name: /2 Original/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
  fireEvent.keyDown(screen.getByRole("dialog"), { key: "1" });
  expect(enhanced.getAttribute("aria-pressed")).toBe("true");
  expect(writes).toHaveLength(0);
});

it("explains absence once and keeps storage machinery out of comparison copy", async () => {
  mount();
  await screen.findByRole("button", { name: /1 Enhanced/ });
  expect(screen.queryByText("A cover has not been added.")).toBeNull();
  expect(
    screen.queryByText(/Stored enhanced derivative|Stored catalogue original/),
  ).toBeNull();
});

it("moves focus to Refresh after a save refusal", async () => {
  failed = true;
  mount();
  const submit = await screen.findByRole("button", { name: "Use this cover" });
  submit.focus();
  fireEvent.click(submit);
  const alert = await screen.findByRole("alert");
  await waitFor(() =>
    expect(document.activeElement).toBe(
      within(alert).getByRole("button", { name: "Refresh choices" }),
    ),
  );
});

it("leaves opener restoration to the owning wall", async () => {
  const opener = document.createElement("button");
  document.body.append(opener);
  opener.focus();
  const restore = vi.spyOn(opener, "focus");
  mount();
  const close = await screen.findByRole("button", {
    name: "Close cover picker",
  });
  close.focus();
  cleanup();
  expect(restore).not.toHaveBeenCalled();
  restore.mockRestore();
  opener.remove();
});

it("keeps web search available and explains a disabled source role", async () => {
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Search the web" }),
  );
  expect(
    await screen.findByText(/Web cover sources are not enabled/),
  ).toBeTruthy();
});
it("searches immediately, lists all sources and retries only the failed source", async () => {
  data.web_sources_enabled = true;
  const posts: Record<string, unknown>[] = [];
  const sourceStates = [
    "empty",
    "rate_limited",
    "empty",
    "unavailable",
    "challenged",
    "busy",
    "not_needed",
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      if (String(input).includes("/searches")) {
        if (init.method === "POST") {
          const body = JSON.parse(String(init.body));
          posts.push(body);
          return new Response(
            JSON.stringify({
              id: "00000000-0000-4000-8000-000000000088",
              entry_id: entry.id,
              query: body.query,
              state: "complete",
              candidate_count: 0,
              sources: body.sources.map((id: string) => ({
                id,
                ...(id === "apple"
                  ? { title_results: 2, title_mismatch: 2 }
                  : {}),
                name: (
                  {
                    apple: "Apple Books",
                    google: "Google Books",
                    openlibrary: "Open Library",
                    hardcover: "Hardcover",
                    goodreads: "Goodreads",
                    lexicanum_live: "Lexicanum (live)",
                    lexicanum: "Lexicanum",
                  } as Record<string, string>
                )[id],
                state:
                  sourceStates[
                    [
                      "apple",
                      "google",
                      "openlibrary",
                      "hardcover",
                      "goodreads",
                      "lexicanum_live",
                      "lexicanum",
                    ].indexOf(id)
                  ],
              })),
            }),
            { status: 202 },
          );
        }
        return new Response(JSON.stringify({ enabled: true, search: null }));
      }
      return new Response(JSON.stringify(data));
    }),
  );
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Search the web" }),
  );
  await waitFor(() => expect(posts).toHaveLength(1));
  expect(posts[0].sources).toEqual([
    "apple",
    "google",
    "openlibrary",
    "hardcover",
    "goodreads",
    "lexicanum_live",
    "lexicanum",
  ]);
  expect(posts[0].query).toEqual({
    title: entry.title,
    author: entry.authors.join(", "),
    isbn: "",
  });
  expect(
    screen.getByText("Refine search").parentElement?.hasAttribute("open"),
  ).toBe(false);
  expect(await screen.findByText(/Open Library: No covers found/)).toBeTruthy();
  expect(
    screen.getByText(
      /Apple Books: Results found, but none matched this title\./,
    ),
  ).toBeTruthy();
  expect(screen.queryByText(/Apple Books: No covers found/)).toBeNull();
  expect(
    screen.getByText(/Hardcover: Unavailable: access was rejected/),
  ).toBeTruthy();
  expect(
    screen.getByText(/Lexicanum \(archived copy\): Not needed/),
  ).toBeTruthy();
  expect(screen.getByText(/Goodreads: Challenged/)).toBeTruthy();
  expect(screen.getByText(/Lexicanum \(live\): Busy/)).toBeTruthy();
  fireEvent.click(screen.getByRole("button", { name: "Retry Google Books" }));
  await waitFor(() => expect(posts).toHaveLength(2));
  expect(posts[1].sources).toEqual(["google"]);
  expect(screen.getByText(/Open Library: No covers found/)).toBeTruthy();
  expect(
    screen
      .getByRole("button", { name: /1 Enhanced/ })
      .getAttribute("aria-pressed"),
  ).toBe("true");
});

it("says no title matched only when every result was dropped for its title", async () => {
  data.web_sources_enabled = true;
  const names: Record<string, string> = {
    apple: "Apple Books",
    google: "Google Books",
    openlibrary: "Open Library",
    hardcover: "Hardcover",
    goodreads: "Goodreads",
    lexicanum_live: "Lexicanum (live)",
    lexicanum: "Lexicanum (archived copy)",
  };
  const rows: Record<string, unknown>[] = [
    { id: "apple", state: "empty", title_results: 2, title_mismatch: 2 },
    { id: "google", state: "empty", title_results: 2, title_mismatch: 1 },
    { id: "openlibrary", state: "empty" },
    { id: "hardcover", state: "partial", title_results: 3, title_mismatch: 3 },
    { id: "goodreads", state: "partial", title_results: 3, title_mismatch: 1 },
    { id: "lexicanum_live", state: "partial" },
    { id: "lexicanum", state: "empty", title_results: 0, title_mismatch: 0 },
  ];
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string) => {
      if (String(input).includes("/searches"))
        return new Response(
          JSON.stringify({
            enabled: true,
            search: {
              id: "00000000-0000-4000-8000-000000000089",
              entry_id: entry.id,
              query: { title: entry.title, author: "", isbn: "" },
              state: "complete",
              candidate_count: 0,
              sources: rows.map((r) => ({ ...r, name: names[String(r.id)] })),
            },
          }),
        );
      return new Response(JSON.stringify(data));
    }),
  );
  mount();
  const line = async (name: string) =>
    (await screen.findByText(new RegExp(`^${name}:`))).textContent ?? "";
  const mismatch = /Results found, but none matched this title/;
  const ordinary = /No covers found/;
  const partial = /Partial coverage/;
  expect(await line("Apple Books")).toMatch(mismatch);
  expect(await line("Apple Books")).not.toMatch(ordinary);
  expect(await line("Google Books")).toMatch(ordinary);
  expect(await line("Google Books")).not.toMatch(mismatch);
  expect(await line("Open Library")).toMatch(ordinary);
  expect(await line("Open Library")).not.toMatch(mismatch);
  expect(await line("Hardcover")).toMatch(partial);
  expect(await line("Hardcover")).toMatch(mismatch);
  expect(await line("Goodreads")).toMatch(partial);
  expect(await line("Goodreads")).not.toMatch(mismatch);
  expect(await line("Lexicanum \\(live\\)")).toMatch(partial);
  expect(await line("Lexicanum \\(live\\)")).not.toMatch(mismatch);
  expect(await line("Lexicanum \\(archived copy\\)")).toMatch(ordinary);
  expect(await line("Lexicanum \\(archived copy\\)")).not.toMatch(mismatch);
});
it("announces all pending sources and keeps refinement collapsed during search", async () => {
  data.web_sources_enabled = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      if (String(input).includes("/searches")) {
        if (!init.method)
          return new Response(JSON.stringify({ enabled: true, search: null }));
        const body = JSON.parse(String(init.body));
        return new Response(
          JSON.stringify({
            id: "00000000-0000-4000-8000-000000000088",
            entry_id: entry.id,
            query: body.query,
            state: "running",
            candidate_count: 0,
            sources: body.sources.map((id: string) => ({
              id,
              name: id,
              state: "pending",
            })),
          }),
        );
      }
      return new Response(JSON.stringify(data));
    }),
  );
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Search the web" }),
  );
  expect(await screen.findByText("Searching 7 sources…")).toBeTruthy();
  expect(screen.queryByText("Search finished")).toBeNull();
  expect(
    screen.getByText("Refine search").parentElement?.hasAttribute("open"),
  ).toBe(false);
  expect(
    screen.getByRole("button", { name: "Search again" }).closest("details"),
  ).toBeTruthy();
});

it.each(["empty", "failed"])(
  "refreshes or retries only Goodreads with an explicit cache bypass (%s)",
  async (sourceState) => {
    data.web_sources_enabled = true;
    const posts: Record<string, unknown>[] = [];
    vi.stubGlobal(
      "fetch",
      vi.fn(async (input: string, init: RequestInit = {}) => {
        if (String(input).includes("/searches")) {
          if (!init.method)
            return new Response(
              JSON.stringify({ enabled: true, search: null }),
            );
          const body = JSON.parse(String(init.body));
          posts.push(body);
          return new Response(
            JSON.stringify({
              id: "00000000-0000-4000-8000-000000000088",
              entry_id: entry.id,
              query: body.query,
              state: "complete",
              candidate_count: 0,
              sources: body.sources.map((id: string) => ({
                id,
                name: id,
                state: sourceState,
              })),
            }),
          );
        }
        return new Response(JSON.stringify(data));
      }),
    );
    mount();
    fireEvent.click(
      await screen.findByRole("button", { name: "Search the web" }),
    );
    fireEvent.click(
      await screen.findByRole("button", {
        name: sourceState === "empty" ? "Refresh Goodreads" : "Retry goodreads",
      }),
    );
    await waitFor(() => expect(posts).toHaveLength(2));
    expect(posts[1].sources).toEqual(["goodreads"]);
    expect(posts[1].refresh_browser).toBe(true);
    expect(posts[1].query).toEqual(posts[0].query);
  },
);

it("shows unconfigured access separately without a retry and explains partial archives", async () => {
  data.web_sources_enabled = true;
  vi.stubGlobal(
    "fetch",
    vi.fn(async (input: string, init: RequestInit = {}) => {
      if (String(input).includes("/searches")) {
        if (init.method !== "POST")
          return new Response(JSON.stringify({ search: null }));
        return new Response(
          JSON.stringify({
            id: "00000000-0000-4000-8000-000000000088",
            entry_id: entry.id,
            query: JSON.parse(String(init.body)).query,
            state: "complete",
            candidate_count: 0,
            sources: [
              { id: "hardcover", name: "Hardcover", state: "not_configured" },
              {
                id: "lexicanum",
                name: "Lexicanum (archived copy)",
                state: "partial",
              },
            ],
          }),
          { status: 202 },
        );
      }
      return new Response(JSON.stringify(data));
    }),
  );
  mount();
  fireEvent.click(
    await screen.findByRole("button", { name: "Search the web" }),
  );
  expect(await screen.findByText(/Hardcover: Not configured/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Retry Hardcover" })).toBeNull();
  expect(
    screen.getByText(/Lexicanum \(archived copy\): Partial coverage/),
  ).toBeTruthy();
});

it("orders web matches by score and labels weak selectable matches visibly", async () => {
  const web = (n: number, match: number) => ({
    ...choice(n, "Web"),
    method: "web_original",
    match,
    confidence: match < 0.75 ? "possible" : "strong",
    source_name: "Apple Books",
    url: `/api/cover-reviews/${entry.id}/images/00000000-0000-4000-8000-000000000088/${choice(n, "Web").id}`,
  });
  data.default_candidate_id = null;
  data.candidates = [
    web(4, 0.16),
    web(5, 0.45),
    web(6, 0.9),
  ] as typeof data.candidates;
  mount();
  const buttons = await screen.findAllByRole("button", { name: /Apple Books/ });
  expect(buttons.map((b) => b.textContent?.includes("Possible match"))).toEqual(
    [false, true, true],
  );
  expect(buttons.map((b) => b.getAttribute("disabled"))).toEqual([
    null,
    null,
    null,
  ]);
  expect(buttons[1].textContent).toContain("45%");
  fireEvent.click(buttons[2]);
  expect(screen.getAllByText(/Possible match/).length).toBeGreaterThan(2);
});

it("shows catalogue absence alongside web choices and labels suggestions without selecting them", async () => {
  data.default_candidate_id = null;
  data.source = {
    status: "empty",
    reason: "No catalogue entry for this book.",
  };
  data.candidates = [
    {
      ...choice(2, "Original"),
      catalogue_suggestion: true,
      catalogue_confidence: 0.84,
      reason: "Catalogue suggestion; confirm the title and edition.",
    } as ReturnType<typeof choice>,
  ];
  mount();
  expect(
    await screen.findByText("No catalogue entry for this book."),
  ).toBeTruthy();
  expect(screen.getByText(/Catalogue suggestion · 84%/)).toBeTruthy();
  expect(screen.queryByRole("button", { name: "Use this cover" })).toBeNull();
});

it("shows exact catalogue absence above weak suggestions and web results", async () => {
  data.default_candidate_id = null;
  data.source = { status: "complete", reason: "No exact catalogue entry." };
  data.candidates = [
    {
      ...choice(2, "Original"),
      catalogue_suggestion: true,
      catalogue_confidence: 0.73,
    },
    {
      ...choice(3, "Original", false),
      catalogue_suggestion: true,
      catalogue_confidence: 0.73,
    },
    {
      ...choice(4, "Web"),
      method: "web_original",
      source_name: "Apple Books",
      match: 0.73,
      url: `/api/cover-reviews/${entry.id}/images/00000000-0000-4000-8000-000000000088/${choice(4, "Web").id}`,
    } as ReturnType<typeof choice>,
  ] as typeof data.candidates;
  mount();
  const absence = await screen.findByText("No exact catalogue entry.");
  const suggestions = screen.getAllByRole("button", {
    name: /Catalogue suggestion · 73%/,
  });
  expect(
    absence.compareDocumentPosition(suggestions[0]) &
      Node.DOCUMENT_POSITION_FOLLOWING,
  ).toBeTruthy();
  expect(screen.queryAllByRole("button", { pressed: true })).toHaveLength(0);
  expect(screen.queryByRole("button", { name: "Use this cover" })).toBeNull();
  expect(suggestions[1].hasAttribute("disabled")).toBe(true);
  fireEvent.click(suggestions[0]);
  expect(suggestions[0].getAttribute("aria-pressed")).toBe("true");
  expect(writes).toHaveLength(0);
});

it("keeps an explicit unsaved web choice when newer search records replace its ID", async () => {
  const web = (n: number, source: string) => ({
    ...choice(n, "Web"),
    method: "web_original",
    source_name: source,
    match: 0.73,
    url: `/api/cover-reviews/${entry.id}/images/00000000-0000-4000-8000-000000000088/${choice(n, "Web").id}`,
  });
  data.default_candidate_id = null;
  data.candidates = [web(4, "Apple Books")];
  const { client } = mount();
  fireEvent.click(await screen.findByRole("button", { name: /Apple Books/ }));
  data.candidates = [web(5, "Google Books")];
  await client.invalidateQueries({ queryKey: ["cover-choices"] });
  const newest = await screen.findByRole("button", { name: /Google Books/ });
  expect(newest.getAttribute("aria-pressed")).toBe("true");
  expect(screen.getByRole("button", { name: "Use this cover" })).toBeTruthy();
  expect(writes).toHaveLength(0);
  data.candidates = [{ ...web(6, "Open Library"), sha256: "e".repeat(64) }];
  await client.invalidateQueries({ queryKey: ["cover-choices"] });
  expect(
    (await screen.findByRole("button", { name: /Open Library/ })).getAttribute(
      "aria-pressed",
    ),
  ).toBe("false");
  expect(screen.queryByRole("button", { name: "Use this cover" })).toBeNull();
  expect(writes).toHaveLength(0);
});
