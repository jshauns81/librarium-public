import { ApiError } from "./api";

export type AuthorSnapshot = {
  version: string;
  sha256: string;
  fixture: boolean;
};
export type CatalogueComparisonTarget = {
  work: string;
  version: string;
  sha256: string;
};

export function catalogueComparisonTarget(
  work = "",
  version = "",
  sha256 = "",
): CatalogueComparisonTarget | null | undefined {
  if (!work && !version && !sha256) return undefined;
  if (
    !/^[A-Za-z0-9_-]{1,128}$/.test(work) ||
    !/^\d{4}\.\d{2}\.\d{2}\.[1-9]\d{0,8}$/.test(version) ||
    !/^[a-f0-9]{64}$/.test(sha256)
  )
    return null;
  return { work, version, sha256 };
}
export type RecordedSpelling = { name: string; owners: number };
export type AuthorGroup = {
  author: { id: string; name: string; version: string };
  status: "complete" | "truncated";
  canonical_owners: number;
  aliases: RecordedSpelling[];
  alias_count: number;
  matched_aliases: RecordedSpelling[];
  matched_alias_count: number;
};
export type AuthorEvidence = {
  schema_version: "librarium.author-groups.v1";
  snapshot: AuthorSnapshot;
  status: "available" | "missing" | "incompatible" | "invalid";
  groups: AuthorGroup[];
  truncated: boolean;
};

const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const keys = (value: Record<string, unknown>, expected: string[]) =>
  Object.keys(value).length === expected.length &&
  expected.every((key) => Object.hasOwn(value, key));
const count = (value: unknown): value is number =>
  Number.isSafeInteger(value) && (value as number) >= 0;
const text = (value: unknown): value is string =>
  typeof value === "string" &&
  !!value.trim() &&
  Array.from(value).length <= 512 &&
  !/[\p{Cc}\p{Cs}]/u.test(value);
const id = (value: unknown): value is string =>
  typeof value === "string" && /^[1-9]\d{0,18}$/.test(value);

function invalid(): never {
  throw new ApiError(
    "The catalogue returned unsupported author evidence. Retry catalogue; no author group was shown.",
    502,
  );
}

export function sameAuthorSnapshot(
  value: unknown,
  pin: AuthorSnapshot,
): boolean {
  return (
    record(value) &&
    typeof value.fixture === "boolean" &&
    value.version === pin.version &&
    value.sha256 === pin.sha256 &&
    value.fixture === pin.fixture
  );
}

function spellings(value: unknown, limit: number): value is RecordedSpelling[] {
  return (
    Array.isArray(value) &&
    value.length <= limit &&
    new Set(value.map((entry) => entry?.name)).size === value.length &&
    value.every(
      (entry) =>
        record(entry) &&
        keys(entry, ["name", "owners"]) &&
        text(entry.name) &&
        count(entry.owners) &&
        entry.owners > 0,
    )
  );
}

export function decodeAuthorEvidence(
  value: unknown,
  pin: AuthorSnapshot,
  authors: { id: string | number; name: string; version?: string }[],
): AuthorEvidence | undefined {
  if (value === undefined) return undefined;
  if (
    !record(value) ||
    !keys(value, [
      "schema_version",
      "snapshot",
      "status",
      "groups",
      "truncated",
    ]) ||
    value.schema_version !== "librarium.author-groups.v1" ||
    !sameAuthorSnapshot(value.snapshot, pin) ||
    !record(value.snapshot) ||
    !keys(value.snapshot, ["version", "sha256", "fixture"]) ||
    !["available", "missing", "incompatible", "invalid"].includes(
      value.status as string,
    ) ||
    typeof value.truncated !== "boolean" ||
    !Array.isArray(value.groups) ||
    value.groups.length > 64 ||
    (value.truncated && value.groups.length !== 64) ||
    (value.status !== "available" &&
      (value.groups.length !== 0 || value.truncated))
  )
    invalid();
  const seen = new Set<string>();
  for (const group of value.groups) {
    if (
      !record(group) ||
      !keys(group, [
        "author",
        "status",
        "canonical_owners",
        "aliases",
        "alias_count",
        "matched_aliases",
        "matched_alias_count",
      ]) ||
      !record(group.author) ||
      !keys(group.author, ["id", "name", "version"]) ||
      !id(group.author.id) ||
      !text(group.author.name) ||
      group.author.version !== pin.version ||
      seen.has(group.author.id) ||
      !authors.some(
        (author) =>
          String(author.id) === (group.author as Record<string, unknown>).id &&
          author.name === (group.author as Record<string, unknown>).name &&
          author.version === pin.version,
      ) ||
      !count(group.canonical_owners) ||
      group.canonical_owners < 1 ||
      !count(group.alias_count) ||
      !count(group.matched_alias_count) ||
      group.matched_alias_count > group.alias_count ||
      !spellings(group.aliases, 32) ||
      !spellings(group.matched_aliases, 8) ||
      group.aliases.length !== Math.min(group.alias_count, 32) ||
      group.matched_aliases.length !== Math.min(group.matched_alias_count, 8) ||
      group.status !==
        (group.alias_count > 32 || group.matched_alias_count > 8
          ? "truncated"
          : "complete") ||
      group.matched_aliases.some((match) => {
        const alias = (group.aliases as RecordedSpelling[]).find(
          (entry) => entry.name === match.name,
        );
        return alias
          ? alias.owners !== match.owners
          : (group.alias_count as number) <= 32;
      })
    )
      invalid();
    seen.add(group.author.id);
  }
  return value as AuthorEvidence;
}

export function decodeCatalogueAuthors<T>(
  value: T,
  pin: AuthorSnapshot,
  selection: { page: number; author?: string } | { work: string },
): T & { author_evidence?: AuthorEvidence } {
  if (!record(value) || !sameAuthorSnapshot(value.snapshot, pin)) invalid();
  const authors: { id: string | number; name: string; version?: string }[] = [];
  const addAuthors = (work: unknown) => {
    if (
      !record(work) ||
      typeof work.id !== "string" ||
      !/^[A-Za-z0-9_-]{1,128}$/.test(work.id) ||
      !text(work.title) ||
      !Array.isArray(work.authors)
    )
      invalid();
    if (work.authors.length > 512) invalid();
    const seenAuthors = new Set<string>();
    for (const author of work.authors) {
      if (
        !record(author) ||
        !text(author.name) ||
        !(
          id(author.id) ||
          (Number.isSafeInteger(author.id) && (author.id as number) > 0)
        ) ||
        seenAuthors.has(String(author.id))
      )
        invalid();
      if (author.version !== undefined && author.version !== pin.version)
        invalid();
      authors.push(author as (typeof authors)[number]);
      seenAuthors.add(String(author.id));
    }
  };
  if ("page" in selection) {
    if (
      !Array.isArray(value.works) ||
      value.works.length > 24 ||
      value.page !== selection.page ||
      value.page_size !== 24 ||
      !count(value.total)
    )
      invalid();
    const seen = new Set<unknown>();
    for (const work of value.works) {
      addAuthors(work);
      if (seen.has(work.id)) invalid();
      seen.add(work.id);
    }
    if (value.selected_author != null) {
      const author = value.selected_author;
      if (
        !record(author) ||
        !(
          id(author.id) ||
          (Number.isSafeInteger(author.id) && (author.id as number) > 0)
        ) ||
        String(author.id) !== selection.author ||
        author.version !== pin.version ||
        !text(author.name)
      )
        invalid();
      authors.push(author as (typeof authors)[number]);
    }
  } else {
    if (value.id !== selection.work) invalid();
    addAuthors(value);
  }
  const evidence = decodeAuthorEvidence(value.author_evidence, pin, authors);
  if (evidence?.status === "available") {
    if (
      "work" in selection &&
      !evidence.truncated &&
      new Set(authors.map((author) => String(author.id))).size !==
        evidence.groups.length
    )
      invalid();
    if (
      "page" in selection &&
      value.selected_author &&
      !evidence.groups.some((group) => group.author.id === selection.author)
    )
      invalid();
  }
  return value as T & { author_evidence?: AuthorEvidence };
}
