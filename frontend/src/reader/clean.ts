// Every document a book frame can show passes through here before the engine
// turns it into a blob: URL. The reader page's Content-Security-Policy is the
// barrier that stops script; this removes active content so a hostile book has
// nothing to try, and keeps links from leaving with access to the reader.
//
// The rules follow the old in-page reader (epub.ts): name what may stay, drop
// whole elements that can run or embed anything, and accept URLs by scheme.

const SVG = "http://www.w3.org/2000/svg";
const XLINK = "http://www.w3.org/1999/xlink";
const XML = "http://www.w3.org/XML/1998/namespace";

// Elements removed with everything inside them, in any namespace.
const DROP = new Set([
  "script",
  "noscript",
  "base",
  "iframe",
  "frame",
  "frameset",
  "object",
  "embed",
  "applet",
  "portal",
  "fencedframe",
  "form",
  "input",
  "button",
  "select",
  "textarea",
  "video",
  "audio",
  "source",
  "track",
  "foreignobject",
  "animate",
  "animatemotion",
  "animatetransform",
  "set",
  "discard",
  "handler",
  "listener",
]);

// Attributes that hold a URL. Anything else that is not an event handler stays.
const URL_ATTRIBUTES = new Set([
  "href",
  "src",
  "srcset",
  "action",
  "formaction",
  "data",
  "poster",
  "background",
  "cite",
  "longdesc",
  "ping",
  "manifest",
  "codebase",
  "dynsrc",
  "lowsrc",
]);

const LINK_SCHEMES = new Set(["blob", "http", "https", "mailto"]);
const RESOURCE_SCHEMES = new Set(["blob"]);

function scheme(value: string) {
  // Browsers ignore control characters and whitespace inside a scheme.
  const compact = value.replace(/[\u0000- \u007f]+/g, "");
  return /^([a-z][a-z0-9+.-]*):/i.exec(compact)?.[1].toLowerCase() ?? null;
}

function allowedUrl(value: string, link: boolean) {
  const found = scheme(value);
  if (!found) return true; // relative, or a fragment within the book
  if (link) return LINK_SCHEMES.has(found);
  if (found === "data")
    return /^data:image\/(png|jpeg|gif|webp|avif|svg\+xml)[;,]/i.test(
      value.trim(),
    );
  return RESOURCE_SCHEMES.has(found);
}

function allowedSrcset(value: string) {
  return value
    .split(",")
    .map((candidate) => candidate.trim().split(/\s+/)[0] ?? "")
    .every((url) => !url || allowedUrl(url, false));
}

function cleanElement(element: Element) {
  const name = element.localName.toLowerCase();
  if (name === "meta" && element.hasAttribute("http-equiv")) {
    element.remove();
    return;
  }
  if (name === "link") {
    const rel = (element.getAttribute("rel") ?? "").toLowerCase().split(/\s+/);
    const href = element.getAttribute("href") ?? "";
    if (!rel.includes("stylesheet") || scheme(href) !== "blob") {
      element.remove();
      return;
    }
  }
  const isLink =
    (name === "a" || name === "area") && element.namespaceURI !== SVG
      ? "html"
      : name === "a"
        ? "svg"
        : null;
  for (const attribute of [...element.attributes]) {
    const local = attribute.localName.toLowerCase();
    const remove = () =>
      element.removeAttributeNS(attribute.namespaceURI, attribute.localName);
    if (local.startsWith("on") || local === "srcdoc") remove();
    else if (attribute.namespaceURI === XML && local === "base") remove();
    else if (local === "srcset") {
      if (!allowedSrcset(attribute.value)) remove();
    } else if (
      URL_ATTRIBUTES.has(local) &&
      (attribute.namespaceURI === null || attribute.namespaceURI === XLINK)
    ) {
      // SVG links may only point inside the book; HTML links may leave it.
      const link = isLink === "html" && local === "href";
      const ok =
        isLink === "svg"
          ? scheme(attribute.value) === null ||
            scheme(attribute.value) === "blob"
          : allowedUrl(attribute.value, link);
      if (!ok) remove();
    }
  }
  if (isLink === "html") {
    element.removeAttribute("target");
    element.setAttribute("rel", "noopener noreferrer");
  }
}

/** Removes active content from a parsed document, in place. */
export function cleanDocument(doc: Document) {
  for (const element of [...doc.getElementsByTagName("*")]) {
    if (!element.isConnected) continue;
    if (DROP.has(element.localName.toLowerCase())) element.remove();
    else cleanElement(element);
  }
  // Only stylesheet instructions survive, and only for the book's own files.
  for (const node of [...doc.childNodes])
    if (
      node.nodeType === Node.PROCESSING_INSTRUCTION_NODE &&
      ((node as ProcessingInstruction).target !== "xml-stylesheet" ||
        !/href\s*=\s*["']blob:/i.test((node as ProcessingInstruction).data))
    )
      node.remove();
  return doc;
}

export function isMarkupType(type: string) {
  const essence = type.split(";")[0].trim().toLowerCase();
  return /^[a-z]+\/([a-z0-9.+-]*\+)?(x?html|xml)$/.test(essence);
}

function parserFor(type: string): DOMParserSupportedType {
  const essence = type.split(";")[0].trim().toLowerCase();
  if (essence === "text/html") return "text/html";
  if (essence === "application/xhtml+xml") return "application/xhtml+xml";
  if (essence === "image/svg+xml") return "image/svg+xml";
  return "application/xml";
}

/**
 * The cleaned text of one book document. A document that is not well-formed
 * is read as HTML when it claims to be (X)HTML, the way the engine reads it,
 * and dropped otherwise.
 */
export function cleanMarkup(text: string, type: string): string {
  if (!text.trim()) return "";
  const parser = parserFor(type);
  let doc = new DOMParser().parseFromString(text, parser);
  if (
    parser !== "text/html" &&
    doc.getElementsByTagName("parsererror").length
  ) {
    if (parser !== "application/xhtml+xml") return "";
    doc = new DOMParser().parseFromString(text, "text/html");
  }
  return new XMLSerializer().serializeToString(cleanDocument(doc));
}

/** A link out of the book that is safe to open in a new tab, or null. */
export function safeExternalHref(href: string): string | null {
  try {
    const url = new URL(href);
    return ["http:", "https:", "mailto:"].includes(url.protocol)
      ? url.href
      : null;
  } catch {
    return null;
  }
}
