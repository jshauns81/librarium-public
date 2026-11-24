import { useEffect } from "react";
import { themes } from "./themes";
import {
  applyTheme,
  migrateStoredPreference,
  readPreference,
  themeStorageKey,
} from "./theme";
import { applyRoomPrefs, MOTION_KEY, ROOM_LIGHT_KEY } from "./room-prefs";

/** Keeps the room in step with the device and with choices made in other tabs. */
export function useThemeSync() {
  useEffect(() => {
    migrateStoredPreference();
    const media = window.matchMedia?.("(prefers-color-scheme: dark)");
    function deviceChanged() {
      if (readPreference() === "system") applyTheme(themes, "system");
    }
    function stored(event: StorageEvent) {
      if (event.key === null || event.key === themeStorageKey)
        applyTheme(themes, readPreference());
      if (
        event.key === null ||
        event.key === ROOM_LIGHT_KEY ||
        event.key === MOTION_KEY
      )
        applyRoomPrefs();
    }
    media?.addEventListener?.("change", deviceChanged);
    window.addEventListener("storage", stored);
    return () => {
      media?.removeEventListener?.("change", deviceChanged);
      window.removeEventListener("storage", stored);
    };
  }, []);
}
