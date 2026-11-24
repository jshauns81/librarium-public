// @vitest-environment jsdom
import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { strToU8, zipSync } from "fflate";
import {
  guardBook,
  openArchive,
  openBook,
  ReaderError,
} from "../src/reader/book";

const container = `<?xml version="1.0"?>
<container version="1.0" xmlns="urn:oasis:names:tc:opendocument:xmlns:container">
  <rootfiles><rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/></rootfiles>
</container>`;

function opf(manifest: string, spine: string, extra = "") {
  return `<?xml version="1.0"?>
<package xmlns="http://www.idpf.org/2007/opf" version="3.0" unique-identifier="id">
  <metadata xmlns:dc="http://purl.org/dc/elements/1.1/">
    <dc:identifier id="id">urn:uuid:test</dc:identifier>
    <dc:title>Hostile Book</dc:title><dc:language>en</dc:language>${extra}
  </metadata>
  <manifest>${manifest}</manifest>
  <spine>${spine}</spine>
</package>`;
}

const chapter = `<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml"><head><title>One</title>
<meta http-equiv="refresh" content="0;url=https://example.com/"/>
<script src="evil.js"></script><script>parent.hacked = 1</script></head>
<body onload="parent.hacked = 1"><h1>Chapter One</h1>
<p onclick="parent.hacked = 1">The storm had <a href="javascript:parent.hacked=1">followed</a> them.</p>
<iframe src="https://example.com/"></iframe></body></html>`;

const xmlPage = `<?xml version="1.0"?>
<page xmlns:h="http://www.w3.org/1999/xhtml"><h:script>parent.hacked = 1</h:script><h:p>Words</h:p></page>`;

function epub(files: Record<string, string>) {
  return zipSync(
    Object.fromEntries(
      Object.entries(files).map(([name, value]) => [name, strToU8(value)]),
    ),
  );
}

const hostile = epub({
  mimetype: "application/epub+zip",
  "META-INF/container.xml": container,
  "OEBPS/content.opf": opf(
    `<item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>
     <item id="c2" href="two.xml" media-type="application/xml"/>
     <item id="c3" href="three" media-type=""/>
     <item id="js" href="evil.js" media-type="application/javascript"/>`,
    `<itemref idref="c1"/><itemref idref="c2"/><itemref idref="c3"/>`,
  ),
  "OEBPS/one.xhtml": chapter,
  "OEBPS/two.xml": xmlPage,
  "OEBPS/three": chapter,
  "OEBPS/evil.js": "parent.hacked = 1",
});

const blobs = new Map<string, Blob>();
const createObjectURL = URL.createObjectURL;
const revokeObjectURL = URL.revokeObjectURL;
beforeEach(() => {
  let count = 0;
  URL.createObjectURL = (blob: Blob) => {
    const url = `blob:https://reader.example/${++count}`;
    blobs.set(url, blob);
    return url;
  };
  URL.revokeObjectURL = (url: string) => void blobs.delete(url);
});
afterEach(() => {
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = revokeObjectURL;
  blobs.clear();
});

describe("openArchive", () => {
  it("reads entries as text, blobs and sizes", async () => {
    const archive = openArchive(epub({ "a/b.txt": "hello", "c.css": "p{}" }));
    expect(archive.entries.map((entry) => entry.filename).sort()).toEqual([
      "a/b.txt",
      "c.css",
    ]);
    expect(archive.loadText("a/b.txt")).toBe("hello");
    expect(archive.loadText("missing")).toBeNull();
    expect(archive.getSize("a/b.txt")).toBe(5);
    expect(archive.getSize("missing")).toBe(0);
    const blob = archive.loadBlob("c.css", "text/css")!;
    expect(blob.type).toBe("text/css");
    expect(await blob.text()).toBe("p{}");
    expect(archive.loadBlob("missing")).toBeNull();
  });

  it("refuses files that are not archives", () => {
    expect(() => openArchive(strToU8("not a zip"))).toThrow(ReaderError);
    expect(() => openArchive(strToU8("not a zip"))).toThrow(
      "This file is not a readable EPUB.",
    );
  });

  it("refuses archives that unpack past the cap", () => {
    const big = epub({ "a.txt": "x".repeat(600), "b.txt": "y".repeat(600) });
    expect(() => openArchive(big, 1000)).toThrow(
      "This EPUB is too large to open in the reader.",
    );
    expect(openArchive(big, 2000).getSize("a.txt")).toBe(600);
  });
});

describe("openBook", () => {
  it("opens a book whose every frame document is cleaned", async () => {
    const book = await openBook(hostile);
    expect(book.metadata.title).toBe("Hostile Book");
    expect(book.sections).toHaveLength(3);

    const texts: string[] = [];
    for (const section of book.sections) {
      const url = await section.load();
      const blob = blobs.get(url)!;
      texts.push(await blob.text());
      if (section.id.endsWith("three"))
        expect(blob.type).toBe("application/xhtml+xml");
    }
    for (const text of texts) {
      expect(text).not.toContain("parent.hacked");
      expect(text).not.toMatch(
        /<(\w+:)?script|<iframe|http-equiv|onload|onclick/i,
      );
      expect(text).not.toMatch(/javascript:/i);
    }
    expect(texts[0]).toContain("Chapter One");
    expect(texts[1]).toContain("Words");
    // No script file was ever turned into a URL.
    for (const blob of blobs.values())
      expect(await blob.text()).not.toBe("parent.hacked = 1");
  });

  it("refuses to hand any script to the engine", () => {
    const target = new EventTarget();
    guardBook({ transformTarget: target });
    const detail = { type: "text/javascript", isScript: true, allow: true };
    target.dispatchEvent(new CustomEvent("load", { detail }));
    expect(detail.allow).toBe(false);
    const data = { type: "application/ecmascript", data: "x()" as unknown };
    target.dispatchEvent(new CustomEvent("data", { detail: data }));
    expect(data).toEqual({ type: "text/plain", data: "" });
  });

  it("explains books it cannot show", async () => {
    await expect(openBook(strToU8("nope"))).rejects.toThrow(
      "This file is not a readable EPUB.",
    );
    await expect(
      openBook(epub({ "META-INF/container.xml": container })),
    ).rejects.toThrow("This EPUB has no readable package file.");
    const fixed = epub({
      "META-INF/container.xml": container,
      "OEBPS/content.opf": opf(
        `<item id="c1" href="one.xhtml" media-type="application/xhtml+xml"/>`,
        `<itemref idref="c1"/>`,
        `<meta property="rendition:layout">pre-paginated</meta>`,
      ).replace(
        "<package ",
        '<package prefix="rendition: http://www.idpf.org/vocab/rendition/#" ',
      ),
      "OEBPS/one.xhtml": chapter,
    });
    await expect(openBook(fixed)).rejects.toThrow(
      "This EPUB uses fixed pages, which the reader cannot show yet. Download it to read it in another app.",
    );
  });
});
