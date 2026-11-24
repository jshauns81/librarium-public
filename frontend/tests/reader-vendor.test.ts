import { createHash } from "node:crypto";
import { existsSync, readdirSync, readFileSync } from "node:fs";
import { join } from "node:path";
import { describe, expect, it } from "vitest";
import { EXCLUDED_FOLIATE_MODULES, readerPage } from "../reader-page";

const vendor = join(__dirname, "..", "vendor", "foliate-js");

describe("vendored foliate-js", () => {
  it("matches the recorded upstream file hashes", () => {
    const readme = readFileSync(join(vendor, "README.md"), "utf8");
    const recorded = [
      ...readme.matchAll(/^\| `([^`]+)` \| `([0-9a-f]{64})` \|$/gm),
    ];
    const files = readdirSync(vendor).filter((name) => name !== "README.md");
    expect(recorded.map(([, name]) => name).sort()).toEqual(files.sort());
    for (const [, name, hash] of recorded)
      expect(
        createHash("sha256")
          .update(readFileSync(join(vendor, name)))
          .digest("hex"),
        name,
      ).toBe(hash);
  });

  it("leaves out every module the reader does not ship", () => {
    for (const module of EXCLUDED_FOLIATE_MODULES)
      expect(existsSync(join(vendor, module)), module).toBe(false);
    const plugin = readerPage();
    const resolve = plugin.resolveId as (
      id: string,
      importer?: string,
    ) => unknown;
    expect(resolve("./pdf.js", join(vendor, "view.js"))).toBe(
      "\0librarium-excluded:./pdf.js",
    );
    expect(resolve("./pdf.js", "/elsewhere/view.js")).toBeNull();
    expect(resolve("./epub.js", join(vendor, "view.js"))).toBeNull();
    const load = plugin.load as (id: string) => string | null;
    expect(load("\0librarium-excluded:./pdf.js")).toContain("throw new Error");
  });
});
