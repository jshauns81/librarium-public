export function coverEntry(n: number, reason = "missing", state = "todo") {
  const missing = reason === "missing",
    unresolved = reason === "unresolved";
  const id = `00000000-0000-4000-8000-${String(n).padStart(12, "0")}`;
  return {
    id,
    library_uuid: "synthetic-library",
    book_uuid: `book-${n}`,
    book_id: String(n),
    title:
      [
        "The Lantern Atlas",
        "A Winter Orchard",
        "The Glass Harbour",
        "Letters from the Moon",
      ][n - 1] ?? `Synthetic book ${n}`,
    authors: ["A. Example"],
    revision: 1,
    state,
    changed_since_skipped: false,
    cover_url: missing || unresolved ? null : `/api/cover-reviews/${id}/cover`,
    facts: {
      status: unresolved ? "unresolved" : "known",
      width: missing || unresolved ? null : 600,
      height: missing || unresolved ? null : 900,
      reasons: unresolved
        ? []
        : reason === "small"
          ? ["width_below_1000", "height_below_1200"]
          : [reason],
      media_type: missing || unresolved ? null : "image/jpeg",
    },
  };
}
export function coverQueue(
  entries = [coverEntry(1), coverEntry(2, "generated"), coverEntry(3, "small")],
) {
  return {
    entries,
    state: "todo",
    reason: "",
    inventory: "inventory",
    stale: false,
    page: 1,
    pages: 1,
    page_size: 24,
    total: entries.length,
    counts: { todo: entries.length, done: 0, skipped: 0 },
    census: {
      id: "00000000-0000-4000-8000-000000000099",
      state: "complete",
      total: 5,
      scanned: 5,
      remaining: 0,
      unresolved: 0,
      error: "",
      complete: true,
      identity_issue_count: 0,
    },
  };
}
