import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api, LIBRARY_TIMEOUT } from "./api";
import type { Cover } from "./BookCover";
import { loadPlace } from "./reading";

type Pin = { version: string; sha256: string };
type OwnedBook = {
  id: string;
  uuid?: string | null;
  title: string;
  authors: string[];
  series: string | null;
  series_index: number | null;
  cover: { url: string } | null;
};
type MemberWork = {
  id: string;
  title: string;
  first_published?: string | null;
  series: { id: number | string; name: string; position?: number | null }[];
  cover?: Cover | null;
};
type WorkSeries = {
  id: number | string;
  name: string;
  position?: number | null;
  position_total?: number | null;
};
type Match = {
  status: string;
  identifiers?: { type: string; status: string; work_id?: string }[];
  candidates: {
    work_id: string;
    title_status: string;
    authors_status: string;
    identifier_match: boolean;
  }[];
};

export type StripItem =
  | {
      kind: "owned";
      position: number | null;
      book: OwnedBook;
      work?: MemberWork;
    }
  | { kind: "missing"; position: number | null; work: MemberWork };

const ROMAN: [number, string][] = [
  [1000, "M"],
  [900, "CM"],
  [500, "D"],
  [400, "CD"],
  [100, "C"],
  [90, "XC"],
  [50, "L"],
  [40, "XL"],
  [10, "X"],
  [9, "IX"],
  [5, "V"],
  [4, "IV"],
  [1, "I"],
];

export function roman(value: number) {
  if (!Number.isInteger(value) || value < 1 || value > 3999)
    return String(value);
  let rest = value;
  let out = "";
  for (const [size, mark] of ROMAN)
    while (rest >= size) {
      out += mark;
      rest -= size;
    }
  return out;
}

const normal = (value: string) =>
  value
    .toLowerCase()
    .normalize("NFKD")
    .replace(/[^\p{L}\p{N}]+/gu, " ")
    .trim();

/** The catalogue's order with your books placed in it; your extra books keep their own place. */
export function mergeSeries(
  owned: OwnedBook[],
  members: MemberWork[],
  seriesId: string | null,
): StripItem[] {
  const position = (work: MemberWork) =>
    work.series.find((entry) => String(entry.id) === seriesId)?.position ??
    null;
  const left = [...owned];
  const take = (work: MemberWork) => {
    const at = position(work);
    let index = left.findIndex(
      (book) => at !== null && book.series_index === at,
    );
    if (index < 0)
      index = left.findIndex(
        (book) => normal(book.title) === normal(work.title),
      );
    return index < 0 ? null : left.splice(index, 1)[0];
  };
  const items: StripItem[] = members.map((work) => {
    const book = take(work);
    return book
      ? { kind: "owned", position: position(work), book, work }
      : { kind: "missing", position: position(work), work };
  });
  for (const book of left)
    items.push({ kind: "owned", position: book.series_index, book });
  // One book per numbered place: yours if you own one, otherwise the
  // earliest published (translations and audio editions share the place).
  const numbered = (value: number | null) => value !== null && value > 0;
  const kept = items.filter((item) => {
    if (item.kind === "owned" || !numbered(item.position)) return true;
    const rivals = items.filter((other) => other.position === item.position);
    if (rivals.some((other) => other.kind === "owned")) return false;
    const first = rivals
      .filter(
        (other): other is Extract<StripItem, { kind: "missing" }> =>
          other.kind === "missing",
      )
      .sort((a, b) =>
        (a.work.first_published ?? "9999").localeCompare(
          b.work.first_published ?? "9999",
        ),
      )[0];
    return first === item;
  });
  // Numbered places first; zero and unplaced books follow, as the catalogue lists them.
  const rank = (item: StripItem) =>
    numbered(item.position) ? item.position! : Number.MAX_SAFE_INTEGER;
  return kept
    .map((item, index) => ({ item, index }))
    .sort((a, b) => rank(a.item) - rank(b.item) || a.index - b.index)
    .map(({ item }) => item);
}

export type StripWindow = {
  before: StripItem[];
  shown: StripItem[];
  after: StripItem[];
};

/** Long series show the books around yours; the rest fold into count tiles. */
export function stripWindow(
  items: StripItem[],
  hereIndex: number,
  size = 8,
): StripWindow {
  if (items.length <= size + 2) return { before: [], shown: items, after: [] };
  const at = hereIndex < 0 ? 0 : hereIndex;
  let start = Math.max(0, at - 3);
  const end = Math.min(items.length, start + size);
  start = Math.max(0, end - size);
  return {
    before: items.slice(0, start),
    shown: items.slice(start, end),
    after: items.slice(end),
  };
}

function Fold({ items, label }: { items: StripItem[]; label: string }) {
  if (!items.length) return null;
  const owned = items.filter((item) => item.kind === "owned").length;
  const numbers = items
    .map((item) => item.position)
    .filter(
      (value): value is number => value !== null && Number.isInteger(value),
    );
  const range =
    numbers.length > 1
      ? `${roman(numbers[0])}–${roman(numbers[numbers.length - 1])}`
      : numbers.length
        ? roman(numbers[0])
        : null;
  return (
    <li className="more">
      {range && <b aria-hidden="true">{range}</b>}
      <span>
        {items.length} {label},{" "}
        {owned === items.length
          ? "all on your shelves"
          : owned
            ? `${owned} on your shelves`
            : "none on your shelves"}
        .
      </span>
    </li>
  );
}

export function matchedWork(match: Match | undefined) {
  if (!match) return null;
  // The catalogue's own identifier names the work even when the titles are
  // written differently ("Red Tithe" and "Carcharodons: Red Tithe"), as long
  // as the authors agree. Everything else needs a full match.
  const named = match.identifiers
    ?.filter((entry) => entry.type === "bl_catalog" && entry.status === "same")
    .map((entry) => entry.work_id);
  if (match.status === "disagreement" && named?.length === 1) {
    const row = match.candidates.find(
      (candidate) =>
        candidate.work_id === named[0] &&
        candidate.identifier_match &&
        candidate.authors_status === "same",
    );
    return row ? row.work_id : null;
  }
  if (match.status !== "matched") return null;
  const agreeing = match.candidates.filter(
    (row) => row.title_status === "same" && row.authors_status === "same",
  );
  const byIdentifier = agreeing.filter((row) => row.identifier_match);
  const chosen = byIdentifier.length ? byIdentifier : agreeing;
  return chosen.length === 1 ? chosen[0].work_id : null;
}

export function SeriesStrip({
  book,
  inventory,
  openBook,
}: {
  book: OwnedBook;
  inventory: { token: string };
  openBook: (id: string) => void;
}) {
  const name = book.series;
  const owned = useQuery({
    queryKey: ["direct-library", "series", name, inventory.token],
    enabled: !!name,
    queryFn: ({ signal }) =>
      api<{ books: OwnedBook[] }>(
        `direct-library/series?${new URLSearchParams({ name: name!, inventory: inventory.token })}`,
        { signal, timeout: LIBRARY_TIMEOUT },
      ),
    retry: false,
  });
  const pin = useQuery({
    queryKey: ["series-catalogue"],
    enabled: !!name,
    queryFn: ({ signal }) =>
      api<({ status: "ready" } & Pin) | { status: "not_configured" }>(
        "catalogue",
        { signal },
      ),
    retry: false,
  });
  const ready = pin.data?.status === "ready" ? (pin.data as Pin) : null;
  const match = useQuery({
    queryKey: [
      "series-match",
      book.id,
      inventory.token,
      ready?.version,
      ready?.sha256,
    ],
    enabled: !!ready,
    queryFn: ({ signal }) =>
      api<Match>(
        `direct-library/books/${encodeURIComponent(book.id)}/match?${new URLSearchParams({ inventory: inventory.token, version: ready!.version, sha256: ready!.sha256 })}`,
        { signal },
      ),
    retry: false,
  });
  const workId = matchedWork(match.data);
  const work = useQuery({
    queryKey: ["series-work", workId, ready?.version, ready?.sha256],
    enabled: !!workId && !!ready,
    queryFn: ({ signal }) =>
      api<{ series: WorkSeries[] }>(
        `catalogue/works/${encodeURIComponent(workId!)}?${new URLSearchParams({ version: ready!.version, sha256: ready!.sha256 })}`,
        { signal },
      ),
    retry: false,
  });
  const series =
    work.data?.series.find(
      (entry) => normal(entry.name) === normal(name ?? ""),
    ) ??
    work.data?.series[0] ??
    null;
  const seriesId = series ? String(series.id) : null;
  const members = useQuery({
    queryKey: ["series-members", seriesId, ready?.version, ready?.sha256],
    enabled: !!seriesId && !!ready,
    queryFn: async ({ signal }) => {
      const works: MemberWork[] = [];
      for (let page = 1; page <= 8; page++) {
        const value = await api<{
          works: MemberWork[];
          total: number;
          page_size: number;
        }>(
          `catalogue/works?${new URLSearchParams({ version: ready!.version, sha256: ready!.sha256, series: seriesId!, page: String(page), q: "", author: "" })}`,
          { signal },
        );
        works.push(...value.works);
        if (works.length >= value.total || value.works.length < value.page_size)
          break;
      }
      return works;
    },
    retry: false,
  });
  if (!name || !owned.data?.books.length) return null;
  const items = mergeSeries(owned.data.books, members.data ?? [], seriesId);
  const known = !!members.data?.length;
  const ownedCount = items.filter((item) => item.kind === "owned").length;
  const hereIndex = items.findIndex(
    (item) => item.kind === "owned" && item.book.id === book.id,
  );
  const here = items[hereIndex];
  const view = stripWindow(items, hereIndex);
  return (
    <section className="band series-band" aria-labelledby="series-order">
      <h3 id="series-order" className="band-title">
        {name}, <span className="fl">in order</span>
      </h3>
      <p className="lede">
        {known
          ? `${ownedCount} of ${items.length} on your shelves.`
          : `${ownedCount} on your shelves. The catalogue's full order shows once this book is matched.`}
        {here?.position != null && ` You are here: book ${here.position}.`}
      </p>
      <ol className="order">
        <Fold items={view.before} label="earlier" />
        {view.shown.map((item, index) => (
          <Volume
            lit={
              view.shown.findIndex(
                (entry) => entry.kind === "owned" && entry.book.id === book.id,
              ) >= index
            }
            key={
              item.kind === "owned" ? `b${item.book.id}` : `w${item.work.id}`
            }
            item={item}
            current={item.kind === "owned" && item.book.id === book.id}
            openBook={openBook}
            catalogueHref={
              ready && item.kind === "missing"
                ? `?${new URLSearchParams({ view: "catalogue", cw: item.work.id, cv: ready.version, ch: ready.sha256 })}`
                : null
            }
          />
        ))}
        <Fold items={view.after} label="more" />
      </ol>
      <p className="legend">
        <span className="ll">Lit as far as you have read</span>
        <span className="lr">Your place</span>
        <span>On your shelves</span>
        {known && <span className="lm">Not in your library</span>}
      </p>
    </section>
  );
}

function Volume({
  lit,
  item,
  current,
  openBook,
  catalogueHref,
}: {
  lit: boolean;
  item: StripItem;
  current: boolean;
  openBook: (id: string) => void;
  catalogueHref: string | null;
}) {
  const number =
    item.position !== null && item.position > 0 ? item.position : null;
  const numeral =
    number === null ? "" : Number.isInteger(number) ? roman(number) : number;
  const label = number !== null ? `Book ${number}: ` : "";
  if (item.kind === "missing")
    return (
      <li className={`vol missing${lit ? " lit" : ""}`}>
        <div className="art">
          <span>
            {item.work.title}
            <br />
            is not in your library.
          </span>
          {catalogueHref && <a href={catalogueHref}>See editions</a>}
        </div>
        <div className="num" aria-hidden="true">
          {numeral}
        </div>
        <div className="t">
          <span className="sr">{label}</span>
          {item.work.title}
        </div>
        <div className="s">Not in your library</div>
      </li>
    );
  const place = loadPlace(item.book.id, item.book.uuid ?? undefined);
  const reading = !!place && place.percent > 0 && place.percent < 100;
  const state = current
    ? "This book"
    : place && place.percent >= 100
      ? "Read"
      : reading
        ? `Open at ${place!.chapter || `${place!.percent}%`}`
        : "On your shelf";
  return (
    <li className={`vol${current ? " here" : ""}${lit ? " lit" : ""}`}>
      <button
        type="button"
        className="art"
        aria-current={current ? "page" : undefined}
        aria-label={`${label}${item.book.title}, ${state}`}
        onClick={() => !current && openBook(item.book.id)}
      >
        {item.book.cover ? (
          <img src={item.book.cover.url} alt="" />
        ) : (
          <span className="folio">
            <b>{item.book.title}</b>
            <i>{item.book.authors.join(", ")}</i>
          </span>
        )}
        {reading && <span className="ribbon-mark" aria-hidden="true" />}
      </button>
      <div className="num" aria-hidden="true">
        {numeral}
      </div>
      <div className="t" aria-hidden="true">
        {item.book.title}
      </div>
      <div className="s" aria-hidden="true">
        {state}
      </div>
    </li>
  );
}
