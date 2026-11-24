import { strFromU8, unzipSync } from "fflate";
import { EPUB, type FoliateBook } from "@vendor/foliate/epub.js";
import { cleanMarkup, isMarkupType } from "./clean";

// The engine reads the EPUB through this loader, never through its own zip or
// PDF code. Everything is unpacked once, inside a fixed budget.

export class ReaderError extends Error {}

export const MAX_UNPACKED = 256 * 1024 * 1024;

export type Archive = {
  entries: { filename: string }[];
  loadText(name: string): string | null;
  loadBlob(name: string, type?: string): Blob | null;
  getSize(name: string): number;
};

export function openArchive(bytes: Uint8Array, limit = MAX_UNPACKED): Archive {
  let files: Record<string, Uint8Array>;
  try {
    let total = 0;
    files = unzipSync(bytes, {
      filter: (file) => {
        total += file.originalSize;
        if (total > limit)
          throw new ReaderError(
            "This EPUB is too large to open in the reader.",
          );
        return !file.name.endsWith("/");
      },
    });
  } catch (error) {
    if (error instanceof ReaderError) throw error;
    throw new ReaderError("This file is not a readable EPUB.");
  }
  const get = (name: string) =>
    Object.hasOwn(files, name) ? files[name] : undefined;
  return {
    entries: Object.keys(files).map((filename) => ({ filename })),
    loadText: (name) => {
      const bytes = get(name);
      return bytes ? strFromU8(bytes) : null;
    },
    loadBlob: (name, type = "") => {
      const bytes = get(name);
      return bytes ? new Blob([bytes as BlobPart], { type }) : null;
    },
    getSize: (name) => get(name)?.length ?? 0,
  };
}

const SCRIPT_TYPE =
  /^(application|text)\/(x-)?(java|ecma)script$|^text\/(jscript|livescript)$|^application\/x-javascript$|^text\/vbscript$/;

function essence(type: unknown) {
  return String(type ?? "")
    .split(";")[0]
    .trim()
    .toLowerCase();
}

async function asText(data: unknown) {
  if (typeof data === "string") return data;
  if (data instanceof Blob) return data.text();
  if (data instanceof ArrayBuffer || ArrayBuffer.isView(data))
    return new TextDecoder().decode(data as ArrayBuffer);
  return "";
}

type LoadDetail = { type?: string; isScript?: boolean; allow: boolean };
type DataDetail = { type?: string; data: unknown };

/** Cleans every document the engine turns into a URL and refuses scripts. */
export function guardBook(book: { transformTarget: EventTarget }) {
  book.transformTarget.addEventListener("load", (event) => {
    const detail = (event as CustomEvent<LoadDetail>).detail;
    if (detail.isScript || SCRIPT_TYPE.test(essence(detail.type)))
      detail.allow = false;
  });
  book.transformTarget.addEventListener("data", (event) => {
    const detail = (event as CustomEvent<DataDetail>).detail;
    const type = essence(detail.type);
    if (SCRIPT_TYPE.test(type)) {
      detail.type = "text/plain";
      detail.data = "";
      return;
    }
    if (type && !isMarkupType(type)) return;
    if (type) {
      detail.data = Promise.resolve(detail.data).then(async (data) =>
        cleanMarkup(await asText(data), type),
      );
      return;
    }
    // A browser may sniff an untyped file as a page, so one that looks like
    // markup is cleaned and typed as XHTML; anything else is plain bytes.
    // The engine awaits both the data and the type before making the URL.
    let sniffed = "application/octet-stream";
    const cleaned = Promise.resolve(detail.data).then(async (data) => {
      const text = await asText(data);
      if (!/^\s*</.test(text.replace(/^﻿/, ""))) return data;
      sniffed = "application/xhtml+xml";
      return cleanMarkup(text, sniffed);
    });
    detail.data = cleaned;
    detail.type = cleaned.then(() => sniffed) as unknown as string;
  });
}

export async function openBook(bytes: Uint8Array): Promise<FoliateBook> {
  const archive = openArchive(bytes);
  let book: FoliateBook;
  try {
    book = await new EPUB(archive).init();
  } catch {
    throw new ReaderError("This EPUB has no readable package file.");
  }
  if (book.rendition?.layout === "pre-paginated")
    throw new ReaderError(
      "This EPUB uses fixed pages, which the reader cannot show yet. Download it to read it in another app.",
    );
  if (!book.sections.length)
    throw new ReaderError("This EPUB has no readable chapters.");
  guardBook(book);
  return book;
}
