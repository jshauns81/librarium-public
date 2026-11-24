import type { Plugin } from "vite";

// The vendored foliate-js engine names optional modules (its own zip reader,
// PDF.js, MOBI, FB2, comics, fixed layout, speech) that Librarium does not ship.
// They resolve to a module that refuses to load, so none of them can enter
// the build even though the engine's own loader still mentions them.
export const EXCLUDED_FOLIATE_MODULES = [
  "./vendor/zip.js",
  "./vendor/fflate.js",
  "./comic-book.js",
  "./fb2.js",
  "./pdf.js",
  "./mobi.js",
  "./fixed-layout.js",
  "./tts.js",
];
const PREFIX = "\0librarium-excluded:";

export function readerPage(): Plugin {
  return {
    name: "librarium-reader-page",
    enforce: "pre",
    resolveId(id, importer) {
      if (
        importer?.replaceAll("\\", "/").includes("/vendor/foliate-js/") &&
        EXCLUDED_FOLIATE_MODULES.includes(id)
      )
        return PREFIX + id;
      return null;
    },
    load(id) {
      if (!id.startsWith(PREFIX)) return null;
      const name = JSON.stringify(id.slice(PREFIX.length));
      return `throw new Error("Librarium's reader does not include " + ${name});\nexport {};\n`;
    },
    configureServer(server) {
      // Django serves the reader page at /read/<book>; the dev server does too.
      server.middlewares.use((request, _response, next) => {
        const [path, query] = (request.url ?? "").split("?");
        if (/^\/read\/[^/]+\/?$/.test(path))
          request.url = `/reader.html${query ? `?${query}` : ""}`;
        next();
      });
    },
  };
}
