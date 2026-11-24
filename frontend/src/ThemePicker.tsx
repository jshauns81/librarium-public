import React, { useEffect, useRef, useState } from "react";
import { themes } from "./themes";
import {
  applyTheme,
  readPreference,
  themeStorageKey,
  validPreference,
} from "./theme";

export function ThemePicker() {
  const [preference, setPreference] = useState(readPreference);
  const preferenceRef = useRef(preference);
  const [storageNotice, setStorageNotice] = useState("");

  useEffect(() => {
    applyTheme(themes, preferenceRef.current);
    const media = window.matchMedia("(prefers-color-scheme: dark)");
    function deviceChanged() {
      if (preferenceRef.current === "system") applyTheme(themes, "system");
    }
    function stored(event: StorageEvent) {
      if (event.key !== themeStorageKey && event.key !== null) return;
      const next = validPreference(event.newValue);
      preferenceRef.current = next;
      setPreference(next);
      setStorageNotice("");
      applyTheme(themes, next);
    }
    media.addEventListener?.("change", deviceChanged);
    window.addEventListener("storage", stored);
    return () => {
      media.removeEventListener?.("change", deviceChanged);
      window.removeEventListener("storage", stored);
    };
  }, []);

  function choose(value: string) {
    const next = validPreference(value);
    preferenceRef.current = next;
    setPreference(next);
    applyTheme(themes, next);
    try {
      localStorage.setItem(themeStorageKey, next);
      setStorageNotice("");
    } catch {
      setStorageNotice("Theme changed; preference not saved.");
    }
  }

  return (
    <div className="theme-picker">
      <label htmlFor="theme">Theme</label>
      <select
        id="theme"
        value={preference}
        onChange={(event) => choose(event.target.value)}
        aria-describedby={storageNotice ? "theme-storage" : undefined}
      >
        <option value="system">System</option>
        {Array.from(new Set(themes.map((theme) => theme.family))).map(
          (family) => (
            <optgroup label={family} key={family}>
              {themes
                .filter((theme) => theme.family === family)
                .map((theme) => (
                  <option key={theme.id} value={theme.id}>
                    {theme.name}
                  </option>
                ))}
            </optgroup>
          ),
        )}
      </select>
      <span id="theme-storage" role="status">
        {storageNotice}
      </span>
    </div>
  );
}
