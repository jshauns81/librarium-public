import React, { useEffect, useRef } from "react";
import type { ReaderPrefs } from "../reading";
import { TEXT_SIZES, type Face, type Flow, type ReaderSettings } from "./prefs";

const TONES: { value: ReaderPrefs["tone"]; label: string }[] = [
  { value: "room", label: "Room" },
  { value: "night", label: "Night" },
  { value: "parchment", label: "Parchment" },
  { value: "paper", label: "Paper" },
];

function Choice<T extends string | number>({
  legend,
  name,
  value,
  options,
  onChange,
  className = "reader-segment",
}: {
  legend: string;
  name: string;
  value: T;
  options: { value: T; label: string; className?: string }[];
  onChange: (value: T) => void;
  className?: string;
}) {
  return (
    <fieldset className="reader-setting">
      <legend>{legend}</legend>
      <div className={className}>
        {options.map((option) => (
          <label key={String(option.value)} className={option.className}>
            <input
              type="radio"
              name={name}
              value={String(option.value)}
              checked={value === option.value}
              onChange={() => onChange(option.value)}
            />
            <span>{option.label}</span>
          </label>
        ))}
      </div>
    </fieldset>
  );
}

export function ReaderSettingsPanel({
  settings,
  onChange,
  onClose,
}: {
  settings: ReaderSettings;
  onChange: (next: Partial<ReaderSettings>) => void;
  onClose: () => void;
}) {
  const panel = useRef<HTMLElement>(null);
  useEffect(() => {
    panel.current?.querySelector<HTMLElement>("button, input:checked")?.focus();
  }, []);
  return (
    <section
      ref={panel}
      id="reader-settings"
      className="reader-panel reader-settings"
      aria-label="Text and page settings"
    >
      <div className="reader-panel-head">
        <h2>Text and page</h2>
        <button type="button" className="reader-close" onClick={onClose}>
          Close
        </button>
      </div>
      <div className="reader-setting">
        <span id="reader-size">Text size</span>
        <div role="group" aria-labelledby="reader-size" className="reader-size">
          <button
            type="button"
            aria-label="Smaller text"
            disabled={settings.size === 0}
            onClick={() => onChange({ size: settings.size - 1 })}
          >
            A
          </button>
          <span className="reader-size-value">
            <span className="reader-numeral">{TEXT_SIZES[settings.size]}</span>{" "}
            px
          </span>
          <button
            type="button"
            aria-label="Larger text"
            disabled={settings.size === TEXT_SIZES.length - 1}
            onClick={() => onChange({ size: settings.size + 1 })}
          >
            A
          </button>
        </div>
      </div>
      <Choice<ReaderPrefs["tone"]>
        legend="Page"
        name="tone"
        value={settings.tone}
        className="reader-tones"
        options={TONES.map((tone) => ({
          ...tone,
          className: `swatch swatch-${tone.value}`,
        }))}
        onChange={(tone) => onChange({ tone })}
      />
      <Choice<Face>
        legend="Typeface"
        name="face"
        value={settings.face}
        options={[
          { value: "garamond", label: "Garamond", className: "face-garamond" },
          { value: "literata", label: "Literata", className: "face-literata" },
          { value: "book", label: "The book’s" },
        ]}
        onChange={(face) => onChange({ face })}
      />
      <Choice<Flow>
        legend="Turning"
        name="flow"
        value={settings.flow}
        options={[
          { value: "paginated", label: "Pages" },
          { value: "scrolled", label: "Scroll" },
        ]}
        onChange={(flow) => onChange({ flow })}
      />
      <Choice<number>
        legend="Line spacing"
        name="spacing"
        value={settings.spacing}
        options={["Close", "Even", "Open"].map((label, value) => ({
          value,
          label,
        }))}
        onChange={(spacing) => onChange({ spacing })}
      />
      <Choice<number>
        legend="Margins"
        name="margins"
        value={settings.margins}
        options={["Slim", "Even", "Broad"].map((label, value) => ({
          value,
          label,
        }))}
        onChange={(margins) => onChange({ margins })}
      />
      <Choice<ReaderPrefs["width"]>
        legend="Line length"
        name="width"
        value={settings.width}
        options={[
          { value: "narrow", label: "Book" },
          { value: "wide", label: "Wide" },
        ]}
        onChange={(width) => onChange({ width })}
      />
      <p className="reader-note">Settings are kept in this browser.</p>
    </section>
  );
}
