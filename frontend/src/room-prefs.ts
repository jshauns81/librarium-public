// Room light and motion are per-device choices, applied to the root before
// the app renders so the first paint already matches them.
export const ROOM_LIGHT_KEY = "librarium.room-light";
export const MOTION_KEY = "librarium.motion";

export type RoomLight = "on" | "off";
export type Motion = "device" | "full" | "less";

export function readRoomLight(): RoomLight {
  try {
    return localStorage.getItem(ROOM_LIGHT_KEY) === "off" ? "off" : "on";
  } catch {
    return "on";
  }
}

export function readMotion(): Motion {
  try {
    const value = localStorage.getItem(MOTION_KEY);
    return value === "full" || value === "less" ? value : "device";
  } catch {
    return "device";
  }
}

export function applyRoomPrefs(
  light: RoomLight = readRoomLight(),
  motion: Motion = readMotion(),
) {
  const root = document.documentElement;
  if (light === "off") root.dataset.roomLight = "off";
  else delete root.dataset.roomLight;
  if (motion === "device") delete root.dataset.motion;
  else root.dataset.motion = motion;
}

/** Saves one choice; returns false when this browser will not keep it. */
export function saveRoomPref(key: string, value: string) {
  try {
    localStorage.setItem(key, value);
    return true;
  } catch {
    return false;
  }
}
