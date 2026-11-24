const LABELS: Record<string, string> = {
  lexicanum: "Lexicanum",
  "gw-shop": "Warhammer shop",
  wikidata: "Wikidata",
  fandom: "Fandom",
  openlibrary: "Open Library",
  isbngrid: "ISBNgrid",
  isbndb: "ISBNdb",
  google: "Google Books",
  hardcover: "Hardcover",
  wikipedia: "Wikipedia",
  audible: "Audible",
  goodreads: "Goodreads",
};

export const sourceLabel = (id: string) =>
  Object.hasOwn(LABELS, id) ? LABELS[id] : id;
