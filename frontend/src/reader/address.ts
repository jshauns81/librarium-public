// The reader lives at /read/<book>?inventory=<token>. The first reader used
// /?read=<book>&inventory=<token>; those links are sent here.

export type ReaderAddress = { bookId: string; inventory: string };

export function readerAddress(
  pathname: string,
  search: string,
): ReaderAddress | null {
  const match = /^\/read\/([^/]+)\/?$/.exec(pathname);
  if (!match) return null;
  let bookId: string;
  try {
    bookId = decodeURIComponent(match[1]);
  } catch {
    return null;
  }
  const inventory = new URLSearchParams(search).get("inventory") ?? "";
  return bookId && inventory ? { bookId, inventory } : null;
}

export function readerHref(bookId: string, inventory: string) {
  return `/read/${encodeURIComponent(bookId)}?${new URLSearchParams({ inventory })}`;
}

/** Where an old /?read= link now points, or null if it is not one. */
export function legacyReaderHref(search: string) {
  const query = new URLSearchParams(search);
  const bookId = query.get("read");
  return bookId ? readerHref(bookId, query.get("inventory") ?? "") : null;
}
