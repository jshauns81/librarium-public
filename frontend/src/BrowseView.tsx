import React, { useEffect, useState } from "react";

type View = "shelves" | "list";
const storageKey = "librarium.browse-view";
const validView = (value: string | null): View =>
  value === "list" ? "list" : "shelves";

export function useBrowseView() {
  const [view, setView] = useState<View>(() => {
    try {
      return validView(localStorage.getItem(storageKey));
    } catch {
      return "shelves";
    }
  });
  const [notice, setNotice] = useState("");
  useEffect(() => {
    function stored(event: StorageEvent) {
      if (event.key !== storageKey && event.key !== null) return;
      setView(validView(event.newValue));
      setNotice("");
    }
    window.addEventListener("storage", stored);
    return () => window.removeEventListener("storage", stored);
  }, []);
  function choose(next: View) {
    setView(next);
    try {
      localStorage.setItem(storageKey, next);
      setNotice("");
    } catch {
      setNotice("View changed; preference not saved.");
    }
  }
  return { view, choose, notice };
}

export function BrowseView({
  view,
  choose,
  notice,
}: ReturnType<typeof useBrowseView>) {
  return (
    <div className="browse-view">
      <div role="group" aria-label="Book presentation">
        <button
          type="button"
          aria-pressed={view === "shelves"}
          onClick={() => choose("shelves")}
        >
          Shelves
        </button>
        <button
          type="button"
          aria-pressed={view === "list"}
          onClick={() => choose("list")}
        >
          List
        </button>
      </div>
      {notice && <span role="status">{notice}</span>}
    </div>
  );
}
