import React, { useEffect, useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { api, LIBRARY_TIMEOUT } from "./api";
import type { Job } from "./types";
import { coverRoom, type CoverRoom } from "./reading";
import { SeriesStrip, roman } from "./SeriesStrip";
import { checkedSound } from "./seal";
import { readerHref } from "./reader/address";
import sealUrl from "./assets/librarium-seal.png";
import emblemUrl from "./assets/archivist.svg";
import "./book-room.css";
import "./home.css";

type Inventory = { token: string; observed_at: string };
type Book = {
  id: string;
  uuid?: string | null;
  title: string;
  authors: string[];
  series: string | null;
  series_index: number | null;
  added_at?: string | null;
  cover: { url: string } | null;
  description?: string | null;
  formats: { format: string; available: boolean | null; name: string }[];
};
type Listing = { inventory: Inventory; total: number; books: Book[] };
type Place = {
  id: string;
  uuid?: string;
  percent: number;
  chapter?: string;
  at?: string;
};

const PLACE_PREFIX = "librarium-reading:";

/** The book you were last reading on this device, if any is open. */
export function lastOpenPlace(storage: Storage = localStorage): Place | null {
  let best: Place | null = null;
  try {
    for (let index = 0; index < storage.length; index++) {
      const key = storage.key(index);
      if (!key?.startsWith(PLACE_PREFIX)) continue;
      const value = JSON.parse(storage.getItem(key) ?? "null");
      const id = key.slice(PLACE_PREFIX.length);
      if (
        !value ||
        !/^[1-9][0-9]{0,18}$/.test(id) ||
        typeof value.percent !== "number" ||
        value.percent <= 0 ||
        value.percent >= 100
      )
        continue;
      const place = { ...value, id } as Place;
      if (!best || String(place.at ?? "") > String(best.at ?? "")) best = place;
    }
  } catch {
    return best;
  }
  return best;
}

/** The greeting comes from the clock and nothing else. */
export function greeting(now: Date) {
  const hour = now.getHours();
  const day = now.toLocaleDateString(undefined, { weekday: "long" });
  const part =
    hour < 5
      ? "night"
      : hour < 12
        ? "morning"
        : hour < 18
          ? "afternoon"
          : hour < 22
            ? "evening"
            : "night";
  return {
    part,
    opening: part === "night" ? `Late on ${day}.` : `${day} ${part}.`,
    margin:
      part === "night"
        ? "Tonight"
        : part === "evening"
          ? "This evening"
          : `This ${part}`,
  };
}

const WORDS: Record<string, number> = {
  one: 1,
  two: 2,
  three: 3,
  four: 4,
  five: 5,
  six: 6,
  seven: 7,
  eight: 8,
  nine: 9,
  ten: 10,
  eleven: 11,
  twelve: 12,
  thirteen: 13,
  fourteen: 14,
  fifteen: 15,
  sixteen: 16,
  seventeen: 17,
  eighteen: 18,
  nineteen: 19,
  twenty: 20,
};

/** A chapter number for the ribbon, only when the chapter's own label gives one. */
export function chapterNumber(label: string | undefined) {
  const text = label?.trim().toLowerCase() ?? "";
  const digits = text.match(/^(?:chapter\s+)?(\d{1,3})\b/);
  if (digits) return Number(digits[1]);
  const word = text.match(/^(?:chapter\s+)?([a-z]+)$/);
  return word && WORDS[word[1]] ? WORDS[word[1]] : null;
}

export function useRootRoom(url: string | undefined) {
  const [room, setRoom] = useState<CoverRoom | null>(null);
  useEffect(() => {
    setRoom(null);
    if (!url) return;
    let current = true;
    coverRoom(url).then((value) => current && setRoom(value));
    return () => {
      current = false;
    };
  }, [url]);
  useEffect(() => {
    if (!room) return;
    const root = document.documentElement;
    root.style.setProperty("--mood-deep", room.deep);
    root.style.setProperty("--mood-light", room.light);
    return () => {
      root.style.removeProperty("--mood-deep");
      root.style.removeProperty("--mood-light");
    };
  }, [room]);
  return room;
}

const dayMonth = (value: string) =>
  new Date(value).toLocaleDateString(undefined, {
    day: "numeric",
    month: "short",
  });

/** "2026.10.24.2" is the 24 October edition; anything else is shown as recorded. */
export function editionName(version: string | undefined) {
  const match = version?.match(/^(\d{4})\.(\d{2})\.(\d{2})(?:\.\d+)?$/);
  if (!match) return version ?? "current";
  return new Date(+match[1], +match[2] - 1, +match[3]).toLocaleDateString(
    undefined,
    { day: "numeric", month: "long" },
  );
}

const sameDay = (value: string) => new Date(value).toDateString();

/** The book open on this device, with the library listing that pins it. */
export function useOpenBook() {
  const place = lastOpenPlace();
  const recent = useQuery({
    queryKey: ["home", "recent"],
    queryFn: ({ signal }) =>
      api<Listing>(
        `direct-library?${new URLSearchParams({ order: "recent" })}`,
        { signal, timeout: LIBRARY_TIMEOUT },
      ),
    retry: false,
  });
  const token = recent.data?.inventory.token;
  const open = useQuery({
    queryKey: ["home", "open", place?.id, token],
    enabled: !!place && !!token,
    queryFn: ({ signal }) =>
      api<{ inventory: Inventory; book: Book }>(
        `direct-library/books/${encodeURIComponent(place!.id)}?${new URLSearchParams({ inventory: token! })}`,
        { signal, timeout: LIBRARY_TIMEOUT },
      ),
    retry: false,
  });
  const book =
    open.data && (!place?.uuid || open.data.book.uuid === place.uuid)
      ? open.data.book
      : null;
  return { place, recent, token, book };
}

export function Home({
  openBook,
  openLibrary,
  now = new Date(),
}: {
  openBook: (id: string, token: string) => void;
  openLibrary: () => void;
  now?: Date;
}) {
  const { place, recent, token, book } = useOpenBook();
  const room = useRootRoom(book?.cover?.url);
  const catalogue = useQuery({
    queryKey: ["home", "catalogue"],
    queryFn: ({ signal }) =>
      api<{ status: string; version?: string; total?: number }>("catalogue", {
        signal,
      }),
    retry: false,
  });
  const checks = useQuery({
    queryKey: ["home", "checks"],
    queryFn: ({ signal }) =>
      api<{ jobs: Job[] }>(
        `jobs/history?${new URLSearchParams({ kind: "epub", page: "1" })}`,
        { signal },
      ),
    retry: false,
  });
  const active = useQuery({
    queryKey: ["home", "active"],
    queryFn: ({ signal }) => api<{ jobs: Job[] }>("jobs", { signal }),
    retry: false,
  });
  const time = greeting(now);
  useEffect(() => {
    const root = document.documentElement;
    if (time.part === "night") root.dataset.late = "";
    return () => {
      delete root.dataset.late;
    };
  }, [time.part]);

  const sound = (checks.data?.jobs ?? []).filter(checkedSound);
  const sealed = sound.find(
    (job) => now.getTime() - new Date(job.updated_at).getTime() < 7 * 864e5,
  );
  const waiting = (active.data?.jobs ?? []).filter((job) =>
    ["queued", "running"].includes(job.state),
  ).length;
  const epub = book?.formats.find(
    (file) => file.format === "EPUB" && file.available,
  );
  const chapter = chapterNumber(place?.chapter);
  const readHref = book && token ? readerHref(book.id, token) : null;

  const arrivals = recent.data?.books ?? [];
  const days = new Map<string, Book[]>();
  for (const entry of arrivals)
    if (entry.added_at) {
      const key = sameDay(entry.added_at);
      days.set(key, [...(days.get(key) ?? []), entry]);
    }
  const chronicle: { at: string; text: string }[] = [];
  for (const [, books] of days)
    chronicle.push({
      at: books[0].added_at!,
      text:
        books.length === 1
          ? `${books[0].title} arrived from Calibre.`
          : `${books.length} books arrived from Calibre, the latest ${books[0].title}.`,
    });
  for (const job of sound.slice(0, 5))
    chronicle.push({
      at: job.updated_at,
      text: `${job.title || "A book"} was checked. Its structure check passed with nothing to fix.`,
    });
  chronicle.sort((a, b) => b.at.localeCompare(a.at));

  return (
    <div className="book-room home">
      <div className="room home-room">
        {room?.haze && <img className="haze" src={room.haze} alt="" />}
        {book ? (
          <div className="desk">
            <figure className="plate">
              {book.cover ? (
                <img className="direct-cover" src={book.cover.url} alt="" />
              ) : (
                <span className="folio-page">
                  <b>{book.title}</b>
                  <i>{book.authors.join(", ")}</i>
                </span>
              )}
              <div className="silk" aria-hidden="true">
                {chapter !== null && (
                  <i>
                    <b>{roman(chapter)}</b>
                  </i>
                )}
              </div>
            </figure>
            <div className="desk-text">
              <p className="when">
                <b>{time.opening}</b> {book.title} is open where you left it
                {place?.chapter
                  ? chapter !== null
                    ? `, at chapter ${place.chapter.replace(/^chapter\s+/i, "").toLowerCase()}`
                    : `, at ${place.chapter}`
                  : ""}
                .
              </p>
              <h1>{book.title}</h1>
              <p className="by">{book.authors.join(", ")}</p>
              {book.series && (
                <p className="series">
                  {book.series}
                  {book.series_index !== null
                    ? ` · Book ${book.series_index}`
                    : ""}
                </p>
              )}
              <div className="place">
                <span className="ch">{place?.chapter ?? "Your place"}</span>
                <span className="pc">{place?.percent}%</span>
                <div
                  className="bar"
                  role="img"
                  aria-label={`${place?.percent} percent read`}
                >
                  <i
                    data-percent={place?.percent}
                    ref={(node) =>
                      node?.style.setProperty(
                        "width",
                        `${place?.percent ?? 0}%`,
                      )
                    }
                  />
                </div>
              </div>
              <div className="direct-read">
                {readHref && epub && (
                  <a className="direct-read-primary" href={readHref}>
                    Resume reading
                  </a>
                )}
                <button
                  type="button"
                  className="direct-read-secondary"
                  onClick={() => token && openBook(book.id, token)}
                >
                  About this book
                </button>
              </div>
            </div>
            <Margin
              heading={time.margin}
              waiting={waiting}
              sealed={sealed}
              book={book}
              token={token}
              openBook={openBook}
            />
          </div>
        ) : (
          <div className="desk desk-empty">
            <div className="desk-text">
              <p className="when">
                <b>{time.opening}</b>{" "}
                {recent.isPending
                  ? "Opening the library…"
                  : "Nothing is open on this device."}
              </p>
              <h1>Choose a book</h1>
              <p className="blurb">
                {recent.data
                  ? `${recent.data.total.toLocaleString()} books are on your shelves. The book you open next lights this room.`
                  : "The book you open next lights this room."}
              </p>
              <div className="direct-read">
                <button
                  type="button"
                  className="direct-read-primary"
                  onClick={openLibrary}
                >
                  Open the library
                </button>
              </div>
            </div>
            <Margin
              heading={time.margin}
              waiting={waiting}
              sealed={sealed}
              book={null}
              token={token}
              openBook={openBook}
            />
          </div>
        )}
        <p className="fold">
          <a href="#below">
            <span>
              Below:{book?.series ? ` ${book.series} in order,` : ""} what
              arrived lately, and the chronicle
            </span>
            <span aria-hidden="true">↓</span>
          </a>
        </p>
      </div>

      <div id="below">
        {book && token && book.series && (
          <SeriesStrip
            book={book}
            inventory={{ token }}
            openBook={(id) => openBook(id, token)}
          />
        )}
        <hr className="rule" />
        <div className="band lately">
          <section aria-labelledby="lately">
            <div className="lately-label">Lately</div>
            <h2 id="lately" className="band-title">
              Lately received
            </h2>
            <p className="lede">
              {arrivals.length
                ? "The newest books in Calibre, by the date they arrived."
                : recent.isPending
                  ? "Reading the library…"
                  : "No arrival dates are recorded."}
            </p>
            <ul className="wall">
              {arrivals.slice(0, 10).map((entry) => (
                <li key={entry.id}>
                  <button
                    type="button"
                    className="art"
                    onClick={() => token && openBook(entry.id, token)}
                    aria-label={`${entry.title}, ${entry.authors.join(", ")}`}
                  >
                    {entry.cover ? (
                      <img src={entry.cover.url} alt="" />
                    ) : (
                      <span className="folio-page">
                        <b>{entry.title}</b>
                      </span>
                    )}
                  </button>
                  <p aria-hidden="true">
                    {entry.title}
                    <i>
                      {entry.authors.join(", ")}
                      {entry.added_at ? ` · ${dayMonth(entry.added_at)}` : ""}
                    </i>
                  </p>
                </li>
              ))}
            </ul>
          </section>
          <aside aria-labelledby="chronicle">
            <h2 id="chronicle" className="band-title">
              Chronicle
            </h2>
            {chronicle.length ? (
              <ol className="chron">
                {chronicle.slice(0, 6).map((entry, index) => (
                  <li key={`${entry.at}:${index}`}>
                    <time className="day" dateTime={entry.at}>
                      <b>{new Date(entry.at).getDate()}</b>
                      <small>
                        {new Date(entry.at).toLocaleDateString(undefined, {
                          month: "short",
                        })}
                      </small>
                    </time>
                    <span>{entry.text}</span>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="lede">Nothing recorded yet.</p>
            )}
          </aside>
        </div>
        <hr className="rule" />
        <footer className="colophon">
          <img src={emblemUrl} alt="" />
          <p className="fin">Librarium</p>
          <p>
            {recent.data
              ? `${recent.data.total.toLocaleString()} books`
              : "Your books"}
            {catalogue.data?.status === "ready" && catalogue.data.total
              ? `, with a catalogue of ${catalogue.data.total.toLocaleString()} Black Library works in its ${editionName(catalogue.data.version)} edition`
              : ""}
            . Your originals in Calibre are never changed.
          </p>
        </footer>
      </div>
    </div>
  );
}

function Margin({
  heading,
  waiting,
  sealed,
  book,
  token,
  openBook,
}: {
  heading: string;
  waiting: number;
  sealed?: Job;
  book: Book | null;
  token?: string;
  openBook: (id: string, token: string) => void;
}) {
  const next = useQuery({
    queryKey: ["home", "next", book?.series, token],
    enabled: !!book?.series && !!token,
    queryFn: ({ signal }) =>
      api<{ books: Book[] }>(
        `direct-library/series?${new URLSearchParams({ name: book!.series!, inventory: token! })}`,
        { signal, timeout: LIBRARY_TIMEOUT },
      ),
    retry: false,
  });
  const after = next.data?.books.find(
    (entry) =>
      book?.series_index != null &&
      entry.series_index != null &&
      entry.series_index > book.series_index,
  );
  return (
    <aside className="margin" aria-label="From the margins">
      <div>
        <h3>{heading}</h3>
        <p>
          {waiting
            ? `${waiting} ${waiting === 1 ? "check is" : "checks are"} running. They need nothing from you.`
            : "Nothing is waiting on you. Read."}
        </p>
      </div>
      {sealed && (
        <div>
          <h3>Sealed lately</h3>
          <div className="sealed-note">
            <img src={sealUrl} alt="" />
            <p>
              {sealed.title || "A book"} was checked on{" "}
              {dayMonth(sealed.updated_at)}. Its structure check passed with
              nothing to fix.
            </p>
          </div>
        </div>
      )}
      {after && token && (
        <div>
          <h3>Next in the series</h3>
          <button
            type="button"
            className="next"
            onClick={() => openBook(after.id, token)}
          >
            {after.cover && <img src={after.cover.url} alt="" />}
            <span>
              <b>{after.title}</b>
              <span>Book {after.series_index}, on your shelves</span>
            </span>
          </button>
        </div>
      )}
    </aside>
  );
}
