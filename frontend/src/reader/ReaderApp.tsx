import React, { useCallback, useEffect, useRef, useState } from "react";
import type { FoliateBook, TocItem } from "@vendor/foliate/epub.js";
import type { View } from "@vendor/foliate/view.js";
import { api } from "../api";
import { coverMood, loadPlace, savePlace } from "../reading";
import { themes } from "../themes";
import type { DirectLibraryBook } from "../DirectLibrary";
import { openBook, ReaderError } from "./book";
import { bookStyles } from "./book-styles";
import { safeExternalHref } from "./clean";
import { placeAt, restoreFrom } from "./place";
import {
  loadSettings,
  MARGINS,
  saveSettings,
  TEXT_SIZES,
  type ReaderSettings,
} from "./prefs";
import { ReaderSettingsPanel } from "./ReaderSettingsPanel";
import { Chevron } from "./Chevron";

type ReaderBook = DirectLibraryBook & { uuid?: string | null };
type Status =
  | { state: "loading" }
  | { state: "ready" }
  | { state: "error"; message: string };
type Where = {
  percent: number;
  chapter: string;
  href: string | null;
  atStart: boolean;
  atEnd: boolean;
};

const WIDE = "(min-width: 64rem)";
const REDUCED = "(prefers-reduced-motion: reduce)";

function useMedia(query: string) {
  const [matches, setMatches] = useState(() => matchMedia(query).matches);
  useEffect(() => {
    const list = matchMedia(query);
    const change = () => setMatches(list.matches);
    change();
    list.addEventListener("change", change);
    return () => list.removeEventListener("change", change);
  }, [query]);
  return matches;
}

function bookHref(bookId: string) {
  return `/?lw=${encodeURIComponent(bookId)}`;
}

function title(book: FoliateBook | null) {
  const value = book?.metadata?.title;
  if (!value) return "";
  return typeof value === "string" ? value : (Object.values(value)[0] ?? "");
}

function flatten(items: TocItem[], depth = 0): (TocItem & { depth: number })[] {
  return items.flatMap((item) => [
    { ...item, depth },
    ...flatten(item.subitems ?? [], depth + 1),
  ]);
}

/** The reading room around one book: chrome, contents and settings. */
export function ReaderApp({
  bookId,
  inventory,
}: {
  bookId: string;
  inventory: string;
}) {
  const [status, setStatus] = useState<Status>({ state: "loading" });
  const [detail, setDetail] = useState<ReaderBook | null>(null);
  const [toc, setToc] = useState<(TocItem & { depth: number })[]>([]);
  const [where, setWhere] = useState<Where | null>(null);
  const [settings, setSettings] = useState(loadSettings);
  const [contents, setContents] = useState(false);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [chrome, setChrome] = useState(true);
  const [mood, setMood] = useState<string | null>(null);
  const [announcement, setAnnouncement] = useState("");
  const [bookTitle, setBookTitle] = useState("");
  const wide = useMedia(WIDE);
  const reduced = useMedia(REDUCED);
  const root = useRef<HTMLDivElement>(null);
  const page = useRef<HTMLDivElement>(null);
  const probe = useRef<HTMLSpanElement>(null);
  const contentsButton = useRef<HTMLButtonElement>(null);
  const settingsButton = useRef<HTMLButtonElement>(null);
  const viewRef = useRef<View | null>(null);
  // Handlers wired into book frames read the latest state through this.
  const live = useRef({ settings, wide, contents, settingsOpen });
  live.current = { settings, wide, contents, settingsOpen };

  const scheme =
    themes.find((theme) => theme.id === document.documentElement.dataset.theme)
      ?.scheme ?? "dark";

  const turn = useCallback((by: 1 | -1) => {
    const view = viewRef.current;
    if (!view) return;
    if (by > 0) void view.next();
    else void view.prev();
  }, []);

  const closePanels = useCallback(() => {
    const {
      contents: open,
      settingsOpen: settingsShown,
      wide: isWide,
    } = live.current;
    if (settingsShown) {
      setSettingsOpen(false);
      settingsButton.current?.focus();
      return true;
    }
    if (open && !isWide) {
      setContents(false);
      contentsButton.current?.focus();
      return true;
    }
    return false;
  }, []);

  const onKey = useCallback(
    (event: KeyboardEvent) => {
      if (
        event.defaultPrevented ||
        event.altKey ||
        event.ctrlKey ||
        event.metaKey
      )
        return;
      const target = event.target as Element | null;
      if (event.key === "Escape") {
        if (closePanels()) event.preventDefault();
        else setChrome(true);
        return;
      }
      if (target?.closest?.("input, select, textarea, .reader-panel")) return;
      const onControl = !!target?.closest?.("button, a");
      const scrolled = live.current.settings.flow === "scrolled";
      const view = viewRef.current;
      if (!view) return;
      let handled = true;
      switch (event.key) {
        case "ArrowRight":
          void view.goRight();
          break;
        case "ArrowLeft":
          void view.goLeft();
          break;
        case "PageDown":
          void view.next();
          break;
        case "PageUp":
          void view.prev();
          break;
        case "ArrowDown":
          void view.next(scrolled ? 80 : undefined);
          break;
        case "ArrowUp":
          void view.prev(scrolled ? 80 : undefined);
          break;
        case " ":
          if (onControl) handled = false;
          else if (event.shiftKey) void view.prev();
          else void view.next();
          break;
        default:
          handled = false;
      }
      if (handled) event.preventDefault();
    },
    [closePanels],
  );

  // A tap on the left or right third turns the page; the middle shows or
  // hides the chrome. Taps on links and selections are left alone.
  const onTap = useCallback(
    (clientX: number, target: Element | null, selection: string) => {
      if (selection || target?.closest?.("a, button, input, label, summary"))
        return;
      const area = page.current?.getBoundingClientRect();
      if (!area || !area.width) return;
      const at = (clientX - area.left) / area.width;
      if (live.current.settings.flow !== "scrolled" && at < 1 / 3) turn(-1);
      else if (live.current.settings.flow !== "scrolled" && at > 2 / 3) turn(1);
      else setChrome((shown) => !shown);
    },
    [turn],
  );

  useEffect(() => {
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onKey]);

  // Lay pages out to the settings and the space available. The page is sized
  // to its text, and shows two pages only when each keeps a comfortable line.
  const layout = useCallback((view: View, current: ReaderSettings) => {
    const renderer = view.renderer;
    const host = page.current;
    const stage = host?.parentElement;
    if (!renderer || !host || !stage) return;
    const em = TEXT_SIZES[current.size] ?? TEXT_SIZES[2];
    const margin = MARGINS[current.margins] ?? MARGINS[1];
    const phone = !matchMedia("(min-width: 48rem)").matches;
    const room = stage.clientWidth - (phone ? 0 : 2 * 72);
    const spread =
      current.flow === "paginated" && room >= 48 * em + 2 * margin + 96;
    const measure = Math.round(
      (spread ? 29 : current.width === "wide" ? 44 : 34) * em,
    );
    const plate = phone
      ? room
      : spread
        ? 2 * measure + 2 * margin + 96
        : measure + margin + 64;
    host.style.setProperty("--plate-width", `${Math.min(room, plate)}px`);
    const attributes: Record<string, string> = {
      flow: current.flow,
      "max-column-count": spread ? "2" : "1",
      "max-inline-size": `${measure}px`,
      "margin-left": `${margin}px`,
      "margin-right": `${margin}px`,
      "margin-top": phone ? "20px" : "36px",
      "margin-bottom": phone ? "20px" : "36px",
      gap: spread ? "7%" : "4%",
    };
    for (const [name, value] of Object.entries(attributes))
      if (renderer.getAttribute(name) !== value)
        renderer.setAttribute(name, value);
    renderer.toggleAttribute("animated", !matchMedia(REDUCED).matches);
    renderer.setAttribute("no-background", "");
    const ink = getComputedStyle(host).color;
    const link = probe.current ? getComputedStyle(probe.current).color : ink;
    renderer.setStyles(
      bookStyles(current, {
        ink,
        link,
        selection: `color-mix(in srgb, ${link} 32%, transparent)`,
        scheme: getComputedStyle(document.documentElement).colorScheme.includes(
          "light",
        )
          ? "light"
          : "dark",
      }),
    );
  }, []);

  // Open the book.
  useEffect(() => {
    const controller = new AbortController();
    const { signal } = controller;
    let view: View | null = null;
    let book: FoliateBook | null = null;
    const query = new URLSearchParams({ inventory });
    (async () => {
      try {
        const info = api<{ book: ReaderBook }>(
          `direct-library/books/${encodeURIComponent(bookId)}?${query}`,
          { signal },
        ).catch(() => null);
        query.set("format", "EPUB");
        const response = await fetch(
          `/api/direct-library/books/${encodeURIComponent(bookId)}/file?${query}`,
          { signal },
        );
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new ReaderError(
            body.error ||
              (response.status === 409
                ? "The library changed since this page opened. Go back and open the book again."
                : `The file could not be read (${response.status}).`),
          );
        }
        book = await openBook(new Uint8Array(await response.arrayBuffer()));
        const found = (await info)?.book ?? null;
        if (signal.aborted) return;
        setDetail(found);
        setBookTitle(found?.title || title(book) || "Untitled book");
        setToc(flatten(book.toc ?? []));
        if (found?.cover?.url)
          coverMood(found.cover.url).then((value) => {
            if (!signal.aborted) setMood(value);
          });

        await import("@vendor/foliate/view.js");
        if (signal.aborted || !page.current) return;
        view = document.createElement("foliate-view") as View;
        view.className = "reader-view";
        page.current.append(view);
        viewRef.current = view;

        view.addEventListener("external-link", (event) => {
          event.preventDefault();
          const href = safeExternalHref(
            String((event as CustomEvent).detail?.href ?? ""),
          );
          if (href) window.open(href, "_blank", "noopener,noreferrer");
          else setAnnouncement("That link cannot be opened from the reader.");
        });
        view.addEventListener("load", (event) => {
          const doc = (event as CustomEvent<{ doc: Document }>).detail.doc;
          doc.addEventListener("keydown", onKey);
          // Middle-clicks and modifier clicks would open a tab around the
          // engine's own link handling; links open only through it.
          doc.addEventListener("auxclick", (click) => {
            if ((click.target as Element)?.closest?.("a"))
              click.preventDefault();
          });
          doc.addEventListener("click", (click) => {
            if (click.defaultPrevented || click.button !== 0) return;
            const frame = doc.defaultView?.frameElement;
            const offset = frame?.getBoundingClientRect().left ?? 0;
            onTap(
              offset + click.clientX,
              click.target as Element,
              doc.getSelection()?.toString() ?? "",
            );
          });
        });

        await view.open(book);
        if (signal.aborted) return;
        const renderer = view.renderer;
        renderer.addEventListener("relocate", (event) => {
          const { index, fraction, reason } = (
            event as CustomEvent<{
              index: number;
              fraction: number;
              reason: string;
            }>
          ).detail;
          const location = view?.lastLocation;
          if (!location) return;
          const chapter = location.tocItem?.label?.trim() ?? "";
          const percent = Math.round((location.fraction ?? 0) * 100);
          setWhere({
            percent,
            chapter,
            href: location.tocItem?.href ?? null,
            atStart: !!(renderer as unknown as { atStart: boolean }).atStart,
            atEnd: !!(renderer as unknown as { atEnd: boolean }).atEnd,
          });
          savePlace(
            bookId,
            placeAt({
              uuid: found?.uuid ?? null,
              index,
              fraction,
              bookFraction: location.fraction ?? 0,
              chapter,
              cfi: location.cfi,
            }),
          );
          if (reason !== "scroll" && reason !== "selection")
            setAnnouncement(
              `${chapter ? `${chapter}. ` : ""}${percent} percent through the book.`,
            );
        });
        layout(view, live.current.settings);

        const target = restoreFrom(
          loadPlace(bookId, found?.uuid ?? null),
          book.sections.length,
        );
        const fromSection = (
          section: { index: number; fraction: number } | null,
        ) =>
          section
            ? renderer.goTo({ index: section.index, anchor: section.fraction })
            : view!.init({ showTextStart: true });
        if (target && "cfi" in target) {
          // A replaced book can leave the exact position pointing nowhere.
          let resolved = false;
          try {
            const at = view.resolveCFI(target.cfi);
            if (
              Number.isInteger(at?.index) &&
              at.index >= 0 &&
              at.index < book.sections.length
            ) {
              await view.init({ lastLocation: target.cfi });
              resolved = true;
            }
          } catch {
            resolved = false;
          }
          if (!resolved && !signal.aborted) await fromSection(target.fallback);
        } else await fromSection(target);
        if (!signal.aborted) setStatus({ state: "ready" });
      } catch (caught) {
        if (signal.aborted) return;
        setStatus({
          state: "error",
          message:
            caught instanceof ReaderError
              ? caught.message
              : "The book could not be opened.",
        });
      }
    })();
    return () => {
      controller.abort();
      view?.close();
      view?.remove();
      book?.destroy();
      if (viewRef.current === view) viewRef.current = null;
    };
    // The page handlers read the latest state through `live`.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [bookId, inventory]);

  // Settings, tone, room light and available space all re-lay the pages.
  useEffect(() => {
    const view = viewRef.current;
    if (view?.renderer) layout(view, settings);
  }, [settings, mood, reduced, contents, wide, status, layout]);

  useEffect(() => {
    const host = page.current;
    if (!host) return;
    let frame = 0;
    const observer = new ResizeObserver(() => {
      cancelAnimationFrame(frame);
      frame = requestAnimationFrame(() => {
        const view = viewRef.current;
        if (view?.renderer) layout(view, live.current.settings);
      });
    });
    observer.observe(host);
    return () => {
      cancelAnimationFrame(frame);
      observer.disconnect();
    };
  }, [layout]);

  useEffect(() => {
    if (mood) root.current?.style.setProperty("--mood", mood);
    else root.current?.style.removeProperty("--mood");
  }, [mood]);

  // Phones show one panel at a time.
  useEffect(() => {
    if (!wide && contents && settingsOpen) setContents(false);
  }, [wide, contents, settingsOpen]);

  function update(next: Partial<ReaderSettings>) {
    const value = { ...settings, ...next };
    setSettings(value);
    saveSettings(value);
  }

  async function goToEntry(href: string) {
    await viewRef.current?.goTo(href);
    if (!wide) {
      setContents(false);
      contentsButton.current?.focus();
    }
  }

  const ready = status.state === "ready";
  const chapter = where?.chapter ?? "";
  const current = where?.href ?? null;
  const displayTitle = detail?.title || bookTitle;

  return (
    <div
      ref={root}
      className="reader"
      data-scheme={scheme}
      data-tone={settings.tone}
      data-flow={settings.flow}
      data-chrome={chrome ? "shown" : "hidden"}
      data-contents={contents ? "open" : "closed"}
      data-mood={mood ? "" : undefined}
    >
      <header className="reader-bar">
        <a
          className="reader-back"
          href={bookHref(bookId)}
          onClick={(event) => {
            if (
              document.referrer.startsWith(location.origin) &&
              history.length > 1
            ) {
              event.preventDefault();
              history.back();
            }
          }}
        >
          <Chevron direction="left" />
          <span>{displayTitle || "Library"}</span>
        </a>
        <p className="reader-where">{chapter}</p>
        <button
          ref={contentsButton}
          type="button"
          className="reader-tool"
          aria-expanded={contents}
          aria-controls="reader-contents"
          disabled={!ready}
          onClick={() => {
            setContents(!contents);
            if (!wide) setSettingsOpen(false);
          }}
        >
          Contents
        </button>
        <button
          ref={settingsButton}
          type="button"
          className="reader-tool reader-aa"
          aria-label="Text and page settings"
          aria-expanded={settingsOpen}
          aria-controls="reader-settings"
          onClick={() => {
            setSettingsOpen(!settingsOpen);
            if (!wide) setContents(false);
          }}
        >
          Aa
        </button>
      </header>

      <div className="reader-body">
        {contents && ready && (
          <nav
            id="reader-contents"
            className="reader-panel reader-contents"
            aria-label="Contents"
          >
            <div className="reader-panel-head">
              <h2>Contents</h2>
              <button
                type="button"
                className="reader-close"
                onClick={() => {
                  setContents(false);
                  contentsButton.current?.focus();
                }}
              >
                Close
              </button>
            </div>
            {toc.length ? (
              <ol>
                {toc.map((entry, index) => (
                  <li
                    key={`${entry.href}-${index}`}
                    className={`depth-${Math.min(entry.depth, 3)}`}
                  >
                    <button
                      type="button"
                      aria-current={entry.href === current ? "true" : undefined}
                      onClick={() => void goToEntry(entry.href)}
                    >
                      {entry.label?.trim() || "Untitled section"}
                    </button>
                  </li>
                ))}
              </ol>
            ) : (
              <p className="reader-note">
                This book has no table of contents. Turn the pages, or use the
                progress below to see how far you are.
              </p>
            )}
          </nav>
        )}

        <main className="reader-stage" aria-label={displayTitle || "Book"}>
          <button
            type="button"
            className="reader-turn reader-turn-prev"
            aria-label="Previous page"
            disabled={!ready || where?.atStart}
            onClick={() => turn(-1)}
          >
            <Chevron direction="left" />
          </button>
          <div
            className="reader-page"
            ref={page}
            onClick={(event) => {
              if (event.target === event.currentTarget)
                onTap(event.clientX, null, "");
            }}
          >
            <span ref={probe} className="reader-probe" aria-hidden="true" />
            {status.state === "loading" && (
              <p className="reader-status" role="status">
                Opening {displayTitle || "the book"}…
              </p>
            )}
            {status.state === "error" && (
              <div className="reader-status" role="alert">
                <h1>This book couldn’t be opened</h1>
                <p>{status.message}</p>
                <a className="reader-status-action" href={bookHref(bookId)}>
                  Back to the book
                </a>
              </div>
            )}
          </div>
          <button
            type="button"
            className="reader-turn reader-turn-next"
            aria-label="Next page"
            disabled={!ready || where?.atEnd}
            onClick={() => turn(1)}
          >
            <Chevron direction="right" />
          </button>
        </main>
      </div>

      <footer className="reader-progress">
        <button
          type="button"
          className="reader-step"
          aria-label="Previous page"
          disabled={!ready || where?.atStart}
          onClick={() => turn(-1)}
        >
          <Chevron direction="left" />
        </button>
        <div className="reader-meter">
          <progress
            max={100}
            value={where?.percent ?? 0}
            aria-label="Progress through the book"
          />
          <span className="reader-percent">
            {where ? `${where.percent}%` : ""}
          </span>
        </div>
        <button
          type="button"
          className="reader-step"
          aria-label="Next page"
          disabled={!ready || where?.atEnd}
          onClick={() => turn(1)}
        >
          <Chevron direction="right" />
        </button>
      </footer>

      {settingsOpen && (
        <ReaderSettingsPanel
          settings={settings}
          onChange={update}
          onClose={() => {
            setSettingsOpen(false);
            settingsButton.current?.focus();
          }}
        />
      )}

      <p className="reader-sr" aria-live="polite">
        {announcement}
      </p>
    </div>
  );
}
