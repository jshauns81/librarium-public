import React, { useRef, useState } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import { api } from "./api";
import { themes, type Theme } from "./themes";
import {
  applyTheme,
  readPreference,
  themeStorageKey,
  validPreference,
} from "./theme";
import { roomTokens } from "./room-tokens";
import { editionName, useOpenBook, useRootRoom } from "./Home";
import { loadPrefs, savePrefs, TEXT_SIZES, type ReaderPrefs } from "./reading";
import {
  applyRoomPrefs,
  MOTION_KEY,
  readMotion,
  readRoomLight,
  ROOM_LIGHT_KEY,
  saveRoomPref,
  type Motion,
  type RoomLight,
} from "./room-prefs";
import "./book-room.css";
import "./settings.css";

/** Each card carries its own room's colours through CSSOM, lit by the open book. */
function paintRoom(node: HTMLElement | null, theme: Theme) {
  if (!node) return;
  for (const [key, value] of Object.entries(theme.colors))
    node.style.setProperty(`--${key}`, value);
  for (const declaration of roomTokens(theme.scheme).split(";")) {
    const at = declaration.indexOf(":");
    if (at > 0)
      node.style.setProperty(
        declaration.slice(0, at).trim(),
        declaration.slice(at + 1).trim(),
      );
  }
}

const ROOM_NOTES: Record<string, string> = {
  light: "Vellum and iron-gall ink",
  dark: "Candlelit, after hours",
};

const ago = (value: string) => {
  const minutes = Math.round((Date.now() - new Date(value).getTime()) / 60000);
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes} minute${minutes === 1 ? "" : "s"} ago`;
  const hours = Math.round(minutes / 60);
  return hours < 48
    ? `${hours} hour${hours === 1 ? "" : "s"} ago`
    : new Date(value).toLocaleDateString();
};

function Segmented<T extends string>({
  name,
  label,
  value,
  options,
  onChange,
}: {
  name: string;
  label: string;
  value: T;
  options: [T, string][];
  onChange: (value: T) => void;
}) {
  return (
    <fieldset className="segmented">
      <legend className="sr">{label}</legend>
      {options.map(([option, text]) => (
        <label key={option}>
          <input
            type="radio"
            name={name}
            value={option}
            checked={value === option}
            onChange={() => onChange(option)}
          />
          <span>{text}</span>
        </label>
      ))}
    </fieldset>
  );
}

export function Settings() {
  const client = useQueryClient();
  const { book, recent } = useOpenBook();
  useRootRoom(book?.cover?.url);
  const [theme, setTheme] = useState(readPreference);
  const [light, setLight] = useState<RoomLight>(readRoomLight);
  const [motion, setMotion] = useState<Motion>(readMotion);
  const [prefs, setPrefs] = useState<ReaderPrefs>(loadPrefs);
  const [notice, setNotice] = useState("");
  const looking = useRef(false);
  const catalogue = useQuery({
    queryKey: ["home", "catalogue"],
    queryFn: ({ signal }) =>
      api<{ status: string; version?: string; total?: number }>("catalogue", {
        signal,
      }),
    retry: false,
  });

  function remember(saved: boolean) {
    setNotice(
      saved ? "" : "Changed for this visit; this browser did not keep it.",
    );
  }
  function chooseTheme(value: string) {
    const next = validPreference(value);
    setTheme(next);
    applyTheme(themes, next);
    try {
      localStorage.setItem(themeStorageKey, next);
      remember(true);
    } catch {
      remember(false);
    }
  }
  function chooseLight(value: RoomLight) {
    setLight(value);
    applyRoomPrefs(value, motion);
    remember(saveRoomPref(ROOM_LIGHT_KEY, value));
  }
  function chooseMotion(value: Motion) {
    setMotion(value);
    applyRoomPrefs(light, value);
    remember(saveRoomPref(MOTION_KEY, value));
  }
  function choosePrefs(next: ReaderPrefs) {
    setPrefs(next);
    savePrefs(next);
  }
  async function lookAgain() {
    if (looking.current) return;
    looking.current = true;
    try {
      await client.invalidateQueries({ queryKey: ["home"] });
      await client.invalidateQueries({ queryKey: ["direct-library"] });
    } finally {
      looking.current = false;
    }
  }

  return (
    <div className="book-room settings">
      <div className="settings-page">
        <nav className="settings-index" aria-label="Settings sections">
          <a href="#room">Reading room</a>
          <a href="#reader">Reader</a>
          <a href="#library">Library</a>
          <a href="#about">About</a>
        </nav>
        <div className="settings-body">
          <h1>Settings</h1>
          <p className="settings-notice" role="status">
            {notice}
          </p>

          <section id="room" aria-labelledby="room-title">
            <h2 id="room-title" className="band-title">
              Reading room
            </h2>
            <p className="lede">
              A room sets the colours. The book you are reading lights it, so
              every room changes with what is open on your desk. The plates, the
              initials and the margin notes stay in every room.
            </p>
            <fieldset className="rooms">
              <legend className="sr">Reading room</legend>
              <label className="room-card follow">
                <input
                  type="radio"
                  name="room"
                  value="system"
                  checked={theme === "system"}
                  onChange={() => chooseTheme("system")}
                />
                <span className="room-name">
                  <b>Follow the device</b>
                  <i>Light when the device is light, Dark when it is dark</i>
                </span>
              </label>
              {themes.map((entry) => (
                <label key={entry.id} className="room-card">
                  <input
                    type="radio"
                    name="room"
                    value={entry.id}
                    checked={theme === entry.id}
                    onChange={() => chooseTheme(entry.id)}
                  />
                  <span
                    className="room-preview"
                    ref={(node) => paintRoom(node, entry)}
                    aria-hidden="true"
                  >
                    <span className="room-light" />
                    {book?.cover && <img src={book.cover.url} alt="" />}
                    <span className="room-text">
                      <i>{book ? "You were reading" : "Nothing open"}</i>
                      <b>{book?.title ?? "Librarium"}</b>
                    </span>
                  </span>
                  <span className="room-name">
                    <b>{entry.name}</b>
                    <i>{ROOM_NOTES[entry.id] ?? entry.family}</i>
                  </span>
                </label>
              ))}
            </fieldset>

            <h3>Light and motion</h3>
            <div className="setting">
              <div>
                <b>Light the room from the book</b>
                <p>
                  The page takes its colour from the cover you are reading. Off
                  keeps the room's own colours.
                </p>
              </div>
              <Segmented
                name="room-light"
                label="Light the room from the book"
                value={light}
                options={[
                  ["on", "On"],
                  ["off", "Off"],
                ]}
                onChange={chooseLight}
              />
            </div>
            <div className="setting">
              <div>
                <b>Motion</b>
                <p>Plates lift and rooms fade between books.</p>
              </div>
              <Segmented
                name="motion"
                label="Motion"
                value={motion}
                options={[
                  ["full", "Full"],
                  ["less", "Less"],
                  ["device", "Follow device"],
                ]}
                onChange={chooseMotion}
              />
            </div>
          </section>

          <section id="reader" aria-labelledby="reader-title">
            <h2 id="reader-title" className="band-title">
              Reader
            </h2>
            <div className="setting">
              <div>
                <b>Page</b>
                <p>The page behind the words while you read.</p>
              </div>
              <Segmented
                name="tone"
                label="Page"
                value={prefs.tone}
                options={[
                  ["room", "Follow the room"],
                  ["night", "Night"],
                  ["parchment", "Parchment"],
                  ["paper", "Paper"],
                ]}
                onChange={(tone) => choosePrefs({ ...prefs, tone })}
              />
            </div>
            <div className="setting">
              <div>
                <b>Text size</b>
                <p>
                  {TEXT_SIZES[prefs.size]} pixels. Each book remembers your
                  place; this sets where every book starts.
                </p>
              </div>
              <div className="steps">
                <button
                  type="button"
                  aria-label="Smaller text"
                  disabled={prefs.size === 0}
                  onClick={() =>
                    choosePrefs({ ...prefs, size: Math.max(0, prefs.size - 1) })
                  }
                >
                  <span className="small-a">A</span>
                </button>
                <button
                  type="button"
                  aria-label="Larger text"
                  disabled={prefs.size === TEXT_SIZES.length - 1}
                  onClick={() =>
                    choosePrefs({
                      ...prefs,
                      size: Math.min(TEXT_SIZES.length - 1, prefs.size + 1),
                    })
                  }
                >
                  <span className="large-a">A</span>
                </button>
              </div>
            </div>
          </section>

          <section id="library" aria-labelledby="library-title">
            <h2 id="library-title" className="band-title">
              Library
            </h2>
            <div className="setting">
              <div>
                <b>
                  {recent.isError
                    ? "Calibre library unavailable"
                    : "Calibre library connected"}
                </b>
                <p>
                  {recent.data
                    ? `${recent.data.total.toLocaleString()} books · read only · looked at ${ago(recent.data.inventory.observed_at)}`
                    : recent.isError
                      ? "Librarium could not read the library just now."
                      : "Reading the library…"}
                </p>
              </div>
              <button
                type="button"
                className="quiet"
                disabled={recent.isFetching}
                onClick={() => void lookAgain()}
              >
                {recent.isFetching ? "Looking…" : "Look again"}
              </button>
            </div>
            <div className="setting">
              <div>
                <b>Writing to Calibre</b>
                <p>
                  Never. Librarium reads and checks your books; it does not
                  change them.
                </p>
              </div>
            </div>
            <div className="setting">
              <div>
                <b>Black Library catalogue</b>
                <p>
                  {catalogue.data?.status === "ready"
                    ? `${editionName(catalogue.data.version)} edition · ${catalogue.data.total?.toLocaleString()} works`
                    : catalogue.isPending
                      ? "Reading the catalogue…"
                      : "No catalogue snapshot is configured."}
                </p>
              </div>
            </div>
          </section>

          <section id="about" aria-labelledby="about-title">
            <h2 id="about-title" className="band-title">
              About
            </h2>
            <p>Librarium beta. Your originals in Calibre are never changed.</p>
          </section>
        </div>
      </div>
    </div>
  );
}
