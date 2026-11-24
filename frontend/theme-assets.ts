import { createHash } from "node:crypto";
import type { Plugin } from "vite";
import { themes } from "./src/themes.ts";
import { applyTheme, themeStorageKey } from "./src/theme.ts";
import { roomTokens } from "./src/room-tokens.ts";

export function themeAssets(): Plugin {
  const css = themes
    .map((theme, i) => {
      const brand = theme.brand ?? {
        ink: theme.colors.ink,
        accent: theme.colors.copper,
        wordmark: theme.colors.ink,
      };
      const colors = {
        ...theme.colors,
        "brand-ink": brand.ink,
        "brand-accent": brand.accent,
        "brand-wordmark": brand.wordmark,
      };
      const declarations = Object.entries(colors)
        .map(([key, value]) => `--${key}:${value};`)
        .join("");
      return `${i === 0 ? ":root," : ""}:root[data-theme="${theme.id}"]{color-scheme:${theme.scheme};${declarations}${roomTokens(theme.scheme)}}`;
    })
    .join("\n");
  const boot = `(()=>{let preference=null;try{preference=localStorage.getItem(${JSON.stringify(themeStorageKey)})}catch{};(${applyTheme.toString()})(${JSON.stringify(themes)},preference)})();`;
  const assets = [
    {
      name: `assets/themes-${createHash("sha256").update(css).digest("hex").slice(0, 12)}.css`,
      source: css,
      type: "text/css",
    },
    {
      name: `assets/theme-boot-${createHash("sha256").update(boot).digest("hex").slice(0, 12)}.js`,
      source: boot,
      type: "text/javascript",
    },
  ];
  return {
    name: "librarium-themes",
    configureServer(server) {
      server.middlewares.use((request, response, next) => {
        const asset = assets.find(
          (entry) => request.url?.split("?")[0] === `/${entry.name}`,
        );
        if (!asset) return next();
        response.setHeader("Content-Type", asset.type);
        response.end(asset.source);
      });
    },
    generateBundle() {
      for (const asset of assets)
        this.emitFile({
          type: "asset",
          fileName: asset.name,
          source: asset.source,
        });
    },
    transformIndexHtml: {
      order: "post",
      handler: () => [
        {
          tag: "link",
          attrs: { rel: "stylesheet", href: `/${assets[0].name}` },
          injectTo: "head",
        },
        {
          tag: "script",
          attrs: { src: `/${assets[1].name}` },
          injectTo: "head",
        },
      ],
    },
  };
}
