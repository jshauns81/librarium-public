// @vitest-environment jsdom
import { afterEach, expect, it, vi } from "vitest";
import {
  decodeEntry,
  decodeQueue,
  fetchQueue,
  fetchSuggestions,
} from "../src/cover-review-api";
import { coverEntry, coverQueue } from "./cover-review-fixtures";

it("binds preview URLs to the selected entry and rejects external art", () => {
  const row = coverEntry(1, "small");
  expect(decodeEntry(row).cover_url).toBe(row.cover_url);
  for (const cover_url of [
    "https://example.com/art.jpg",
    "/api/cover-reviews/another/cover",
    "//example.com/a",
  ])
    expect(() => decodeEntry({ ...row, cover_url })).toThrow();
});
it("validates census completeness, pagination, counts and reasons", () => {
  expect(decodeQueue(coverQueue([])).entries).toEqual([]);
  for (const bad of [
    { counts: { todo: -1, done: 0, skipped: 0 } },
    { page: 0 },
    { stale: "false" },
    {
      entries: [
        { ...coverEntry(1), facts: { status: "known", reasons: ["guessed"] } },
      ],
    },
  ])
    expect(() => decodeQueue({ ...coverQueue([]), ...bad })).toThrow();
});
it("rejects malformed entries and inconsistent completed censuses", () => {
  const entry = coverEntry(1, "small");
  for (const patch of [
    { id: "not-a-uuid" },
    { authors: "Example" },
    { authors: Array(65).fill("Example") },
    { revision: 0 },
    { state: "saved" },
    { title: 42 },
    { changed_since_skipped: null },
    { facts: { ...entry.facts, width: -1 } },
    { facts: { ...entry.facts, status: "guessed" } },
  ])
    expect(() => decodeEntry({ ...entry, ...patch })).toThrow();
  for (const patch of [
    { remaining: 1 },
    { unresolved: 1 },
    { complete: false },
    { state: "invented" },
  ])
    expect(() =>
      decodeQueue({
        ...coverQueue([]),
        census: { ...coverQueue().census, ...patch },
      }),
    ).toThrow();
  expect(() => decodeQueue(null)).toThrow();
  expect(() =>
    decodeQueue({ ...coverQueue(), entries: Array(25).fill(entry) }),
  ).toThrow();
});

afterEach(() => vi.unstubAllGlobals());
it("binds queue replies to the requested tab, reason and page", async () => {
  vi.stubGlobal(
    "fetch",
    vi.fn(() => Promise.resolve(new Response(JSON.stringify(coverQueue())))),
  );
  expect((await fetchQueue("todo", "", 1)).entries).toHaveLength(3);
  await expect(fetchQueue("skipped", "", 1)).rejects.toThrow();
  await expect(fetchQueue("todo", "missing", 1)).rejects.toThrow();
  await expect(fetchQueue("todo", "", 2)).rejects.toThrow();
});
it("batches the page, uses the library deadline and refuses unbound suggestions", async () => {
  const entries = [decodeEntry(coverEntry(1)), decodeEntry(coverEntry(2))];
  const pin = { version: "test.1", sha256: "a".repeat(64) };
  const url = `/api/catalogue/covers/work-one/${"b".repeat(64)}?version=test.1&sha256=${pin.sha256}`;
  const rows = entries.map((e) => ({
    id: e.id,
    revision: e.revision,
    book_id: e.book_id,
    book_uuid: e.book_uuid,
    library_uuid: e.library_uuid,
    work_id: "work-one",
    cover: { url, sha256: "b".repeat(64), width: 1000, height: 1500 },
  }));
  let reply = { inventory: "inventory", snapshot: pin, entries: rows };
  const fetcher = vi.fn((_input: string) =>
    Promise.resolve(new Response(JSON.stringify(reply))),
  );
  vi.stubGlobal("fetch", fetcher);
  const deadline = vi.spyOn(AbortSignal, "timeout");
  const result = await fetchSuggestions(
    entries,
    "inventory",
    pin,
    new AbortController().signal,
  );
  expect(result[entries[0].id]).toEqual({ url, width: 1000, height: 1500 });
  expect(fetcher).toHaveBeenCalledTimes(1);
  const requested = new URL(String(fetcher.mock.calls[0][0]), location.origin);
  expect(requested.pathname).toBe("/api/cover-reviews/suggestions");
  expect(requested.searchParams.getAll("entry")).toEqual(
    entries.map((e) => `${e.id}:${e.revision}`),
  );
  expect(deadline).toHaveBeenCalledWith(20_000);
  for (const patch of [
    { inventory: "changed" },
    { snapshot: { ...pin, sha256: "c".repeat(64) } },
    { entries: [rows[0], rows[0]] },
    { entries: [rows[0]] },
    { entries: [{ ...rows[0], revision: 99 }, rows[1]] },
    { entries: [{ ...rows[0], book_uuid: "changed" }, rows[1]] },
    {
      entries: [
        {
          ...rows[0],
          cover: { ...rows[0].cover, url: "https://example.com/art.jpg" },
        },
        rows[1],
      ],
    },
  ]) {
    reply = { inventory: "inventory", snapshot: pin, entries: rows, ...patch };
    await expect(
      fetchSuggestions(entries, "inventory", pin, new AbortController().signal),
    ).rejects.toThrow();
  }
  deadline.mockRestore();
});
