// @vitest-environment jsdom
import { describe, expect, it } from "vitest";
import {
  cleanMarkup,
  isMarkupType,
  safeExternalHref,
} from "../src/reader/clean";

const XHTML = "application/xhtml+xml";

function parse(text: string, type: DOMParserSupportedType = XHTML) {
  return new DOMParser().parseFromString(text, type);
}

const hostile = `<?xml version="1.0" encoding="utf-8"?>
<html xmlns="http://www.w3.org/1999/xhtml" xmlns:svg="http://www.w3.org/2000/svg"
  xmlns:xlink="http://www.w3.org/1999/xlink">
<head>
  <meta charset="utf-8"/>
  <meta http-equiv="refresh" content="0;url=https://example.com/"/>
  <meta http-equiv="Content-Security-Policy" content="script-src *"/>
  <base href="https://example.com/"/>
  <title>Chapter</title>
  <link rel="stylesheet" href="blob:https://reader.example/sheet"/>
  <link rel="stylesheet" href="https://example.com/remote.css"/>
  <link rel="prefetch" href="https://example.com/track"/>
  <style>p { color: red }</style>
  <script>parent.hacked = 1</script>
  <script src="blob:https://reader.example/evil"></script>
</head>
<body onload="parent.hacked = 1">
  <h1 id="start" class="chapter" style="text-align:center">Chapter One</h1>
  <p onclick="parent.hacked = 1" onmouseover="x()">The <em>storm</em> had followed them.</p>
  <p><a href="javascript:parent.hacked=1">bad</a> <a href=" JaVaScRiPt:alert(1)">spaced</a>
     <a href="vbscript:x">vb</a> <a href="data:text/html,&lt;script&gt;x&lt;/script&gt;">data</a>
     <a href="https://example.com/" target="_blank">site</a>
     <a href="blob:https://reader.example/two#later">next</a> <a href="#start">top</a></p>
  <img src="blob:https://reader.example/pic" alt="A map" onerror="parent.hacked=1"/>
  <img src="javascript:x" alt="bad image"/>
  <img src="data:image/png;base64,AAAA" alt="inline picture"/>
  <img src="data:text/html;base64,AAAA" alt="not a picture"/>
  <iframe src="https://example.com"></iframe>
  <frame src="https://example.com"/>
  <object data="https://example.com/x.swf"></object>
  <embed src="https://example.com/x.swf"/>
  <form action="https://example.com/"><input name="q"/><button formaction="javascript:x">Go</button></form>
  <video src="blob:https://reader.example/v" autoplay="autoplay"></video>
  <svg:svg viewBox="0 0 10 10" onload="parent.hacked=1">
    <svg:script>parent.hacked = 1</svg:script>
    <svg:foreignObject><p xmlns="http://www.w3.org/1999/xhtml">inside</p></svg:foreignObject>
    <svg:a xlink:href="javascript:parent.hacked=1"><svg:text>link</svg:text></svg:a>
    <svg:animate attributeName="href" to="javascript:parent.hacked=1"/>
    <svg:set attributeName="onclick" to="parent.hacked=1"/>
    <svg:image xlink:href="blob:https://reader.example/cover" width="10" height="10"/>
  </svg:svg>
</body>
</html>`;

describe("cleanMarkup", () => {
  it("keeps the story, its styling and its own resources", () => {
    const doc = parse(cleanMarkup(hostile, XHTML));
    expect(doc.querySelector("parsererror")).toBeNull();
    expect(doc.querySelector("h1")?.textContent).toBe("Chapter One");
    expect(doc.querySelector("h1")?.getAttribute("style")).toBe(
      "text-align:center",
    );
    expect(doc.querySelector("h1")?.id).toBe("start");
    expect(doc.querySelector("style")?.textContent).toContain("color: red");
    expect(doc.querySelector("title")?.textContent).toBe("Chapter");
    expect(doc.querySelector("meta[charset]")).not.toBeNull();
    const sheets = [...doc.querySelectorAll("link")].map((link) =>
      link.getAttribute("href"),
    );
    expect(sheets).toEqual(["blob:https://reader.example/sheet"]);
    const images = [...doc.querySelectorAll("img")].map((image) => [
      image.getAttribute("alt"),
      image.getAttribute("src"),
    ]);
    expect(images).toEqual([
      ["A map", "blob:https://reader.example/pic"],
      ["bad image", null],
      ["inline picture", "data:image/png;base64,AAAA"],
      ["not a picture", null],
    ]);
    const svgImage = doc.getElementsByTagNameNS(
      "http://www.w3.org/2000/svg",
      "image",
    )[0];
    expect(
      svgImage.getAttributeNS("http://www.w3.org/1999/xlink", "href"),
    ).toBe("blob:https://reader.example/cover");
  });

  it("removes every script, handler and active element", () => {
    const text = cleanMarkup(hostile, XHTML);
    const doc = parse(text);
    for (const name of [
      "script",
      "base",
      "iframe",
      "frame",
      "object",
      "embed",
      "form",
      "input",
      "button",
      "video",
      "foreignObject",
      "animate",
      "set",
    ])
      expect(doc.getElementsByTagNameNS("*", name).length, name).toBe(0);
    expect(doc.querySelectorAll("meta[http-equiv]").length).toBe(0);
    for (const element of doc.querySelectorAll("*"))
      for (const attribute of element.attributes)
        expect(
          attribute.name.toLowerCase().startsWith("on"),
          attribute.name,
        ).toBe(false);
    expect(text).not.toMatch(/javascript:|vbscript:|data:text\/html/i);
    expect(text).not.toContain("parent.hacked");
    expect(text).not.toContain("example.com/remote.css");
    expect(text).not.toContain("example.com/track");
  });

  it("makes links safe to follow without reaching the reader", () => {
    const doc = parse(cleanMarkup(hostile, XHTML));
    const links = [
      ...doc.getElementsByTagNameNS("http://www.w3.org/1999/xhtml", "a"),
    ].map((link) => [
      link.textContent,
      link.getAttribute("href"),
      link.getAttribute("target"),
      link.getAttribute("rel"),
    ]);
    expect(links).toEqual([
      ["bad", null, null, "noopener noreferrer"],
      ["spaced", null, null, "noopener noreferrer"],
      ["vb", null, null, "noopener noreferrer"],
      ["data", null, null, "noopener noreferrer"],
      ["site", "https://example.com/", null, "noopener noreferrer"],
      [
        "next",
        "blob:https://reader.example/two#later",
        null,
        "noopener noreferrer",
      ],
      ["top", "#start", null, "noopener noreferrer"],
    ]);
    const svgLink = doc.getElementsByTagNameNS(
      "http://www.w3.org/2000/svg",
      "a",
    )[0];
    expect(svgLink.hasAttributeNS("http://www.w3.org/1999/xlink", "href")).toBe(
      false,
    );
  });

  it("cleans documents the XML parser rejects as HTML", () => {
    const broken = `<html><head><script>parent.hacked=1</script></head>
      <body><p onclick="x()">Broken &nbsp; markup<br></p><img src=x onerror=alert(1)></body></html>`;
    const text = cleanMarkup(broken, XHTML);
    expect(text).not.toContain("parent.hacked");
    expect(text).not.toMatch(/onclick|onerror/);
    expect(text).toContain("Broken");
  });

  it("cleans HTML and SVG documents too", () => {
    const html = cleanMarkup(
      `<!doctype html><html><body><p>Words</p><script>x()</script><a href="javascript:x">a</a></body></html>`,
      "text/html",
    );
    expect(html).toContain("Words");
    expect(html).not.toMatch(/<script|javascript:/i);
    const svg = cleanMarkup(
      `<svg xmlns="http://www.w3.org/2000/svg" onload="x()"><script>x()</script><rect width="1" height="1"/></svg>`,
      "image/svg+xml",
    );
    expect(svg).toContain("<rect");
    expect(svg).not.toMatch(/<script|onload/i);
  });

  it("blanks markup it cannot read at all", () => {
    expect(cleanMarkup("", XHTML)).toBe("");
  });
});

describe("isMarkupType", () => {
  it("recognises every type a frame could render as a document", () => {
    for (const type of [
      "application/xhtml+xml",
      "text/html",
      "image/svg+xml",
      "application/xml",
      "text/xml",
      "application/x-dtbook+xml",
      "TEXT/HTML; charset=utf-8",
    ])
      expect(isMarkupType(type), type).toBe(true);
    for (const type of ["text/css", "image/png", "font/woff2", ""])
      expect(isMarkupType(type), type).toBe(false);
  });
});

describe("safeExternalHref", () => {
  it("allows only web and mail links out of the book", () => {
    expect(safeExternalHref("https://example.com/a?b#c")).toBe(
      "https://example.com/a?b#c",
    );
    expect(safeExternalHref("http://example.com/")).toBe("http://example.com/");
    expect(safeExternalHref("mailto:someone@example.com")).toBe(
      "mailto:someone@example.com",
    );
    for (const bad of [
      "javascript:alert(1)",
      " javascript:alert(1)",
      "data:text/html,x",
      "file:///etc/passwd",
      "blob:https://reader.example/x",
      "chrome://settings",
      "not a url",
    ])
      expect(safeExternalHref(bad), bad).toBeNull();
  });
});
