import { expect, test } from "vitest";
import {
  matchedWork,
  mergeSeries,
  roman,
  stripWindow,
} from "../src/SeriesStrip";

const book = (id: string, title: string, series_index: number | null) => ({
  id,
  title,
  authors: ["Dan Abnett"],
  series: "Gaunt's Ghosts",
  series_index,
  cover: null,
});
const work = (id: string, title: string, position: number | null) => ({
  id,
  title,
  series: [{ id: 7, name: "Gaunt's Ghosts", position }],
});

test("owned books take their catalogue place; gaps stay honest", () => {
  const items = mergeSeries(
    [book("10", "Necropolis", 3), book("11", "First and Only", 1)],
    [
      work("w1", "First and Only", 1),
      work("w2", "Ghostmaker", 2),
      work("w3", "Necropolis", 3),
    ],
    "7",
  );
  expect(items.map((item) => [item.kind, item.position])).toEqual([
    ["owned", 1],
    ["missing", 2],
    ["owned", 3],
  ]);
});

test("a book without a matching position is placed by its title", () => {
  const items = mergeSeries(
    [book("12", "Honour  Guard!", null)],
    [work("w4", "Honour Guard", 4)],
    "7",
  );
  expect(items).toHaveLength(1);
  expect(items[0]).toMatchObject({ kind: "owned", position: 4 });
});

test("books the catalogue does not list still appear, after the numbered ones", () => {
  const items = mergeSeries(
    [book("13", "A Ghost Return", null), book("10", "Necropolis", 3)],
    [work("w3", "Necropolis", 3)],
    "7",
  );
  expect(
    items.map((item) => (item.kind === "owned" ? item.book.id : item.work.id)),
  ).toEqual(["10", "13"]);
});

test("without the catalogue, the strip is your own books in their order", () => {
  const items = mergeSeries([book("2", "B", 2), book("1", "A", 1)], [], null);
  expect(items.map((item) => item.position)).toEqual([1, 2]);
});

test("roman numerals for whole positions only", () => {
  expect([1, 4, 9, 14, 16, 40].map(roman)).toEqual([
    "I",
    "IV",
    "IX",
    "XIV",
    "XVI",
    "XL",
  ]);
  expect(roman(2.5)).toBe("2.5");
});

test("a long series folds into tiles around your book", () => {
  const items = mergeSeries(
    Array.from({ length: 16 }, (_, i) =>
      book(String(i + 1), `T${i + 1}`, i + 1),
    ),
    [],
    null,
  );
  const view = stripWindow(items, 9);
  expect(view.shown.map((item) => item.position)).toEqual([
    7, 8, 9, 10, 11, 12, 13, 14,
  ]);
  expect(view.before).toHaveLength(6);
  expect(view.after).toHaveLength(2);
  expect(stripWindow(items.slice(0, 10), 0).before).toHaveLength(0);
});

test("the catalogue identifier names the work despite a differently written title", () => {
  const row = {
    work_id: "w_red",
    title_status: "different",
    authors_status: "same",
    identifier_match: true,
  };
  const ids = [{ type: "bl_catalog", status: "same", work_id: "w_red" }];
  expect(
    matchedWork({
      status: "disagreement",
      identifiers: ids,
      candidates: [row],
    }),
  ).toBe("w_red");
  expect(
    matchedWork({
      status: "disagreement",
      identifiers: ids,
      candidates: [{ ...row, authors_status: "different" }],
    }),
  ).toBeNull();
  expect(
    matchedWork({ status: "disagreement", identifiers: [], candidates: [row] }),
  ).toBeNull();
  expect(
    matchedWork({ status: "ambiguous", identifiers: ids, candidates: [row] }),
  ).toBeNull();
});

test("one book per numbered place, and short stories after the numbered books", () => {
  const items = mergeSeries(
    [book("1", "Red Tithe", 1)],
    [
      { ...work("s", "The Reaping Time", 0), first_published: "2016-12" },
      { ...work("de", "Das Äußere Dunkel", 2), first_published: "2019-06-05" },
      { ...work("en", "Outer Dark", 2), first_published: "2018" },
      {
        ...work("fr", "La noirceur extérieure", 2),
        first_published: "2019-05-17",
      },
      { ...work("red", "Carcharodons: Red Tithe", 1), first_published: "2017" },
      {
        ...work("dup", "Carcharodons: Red Tithe (audio)", 1),
        first_published: "2017",
      },
    ],
    "7",
  );
  expect(
    items.map((item) =>
      item.kind === "owned" ? `own:${item.book.id}` : item.work.id,
    ),
  ).toEqual(["own:1", "en", "s"]);
});
