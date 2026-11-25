import { fileURLToPath } from "node:url";
import { defineConfig } from "vitest/config";
import { themeAssets } from "./theme-assets.ts";
import { readerPage } from "./reader-page.ts";
export default defineConfig({
  plugins: [themeAssets(), readerPage()],
  resolve: {
    alias: {
      "@vendor/foliate": fileURLToPath(
        new URL("./vendor/foliate-js", import.meta.url),
      ),
    },
  },
  build: {
    rolldownOptions: {
      input: {
        main: fileURLToPath(new URL("./index.html", import.meta.url)),
        reader: fileURLToPath(new URL("./reader.html", import.meta.url)),
      },
      onLog(level, log, handler) {
        // This app is entirely client-rendered; React Query's RSC boundary is redundant.
        if (
          log.code === "MODULE_LEVEL_DIRECTIVE" &&
          log.id?.includes("/node_modules/@tanstack/react-query/") &&
          log.message.includes('"use client"')
        )
          return;
        handler(level, log);
      },
    },
  },
  server: {
    host: "127.0.0.1",
    port: 5173,
    strictPort: true,
    proxy: { "/api": "http://127.0.0.1:8123" },
  },
  test: {
    // Sized for runner-pool CPU contention across concurrent CI jobs.
    testTimeout: 30000,
    hookTimeout: 30000,
    setupFiles: ["./tests/setup.ts"],
    include: ["tests/**/*.test.{ts,tsx}"],
    coverage: {
      include: [
        "src/state.ts",
        "src/api.ts",
        "src/App.tsx",
        "src/Catalogue.tsx",
        "src/CatalogueHealth.tsx",
        "src/CatalogueGlance.tsx",
        "src/catalogue-sources.ts",
        "src/CatalogueSupport.tsx",
        "src/Library.tsx",
        "src/LibraryEvidence.tsx",
        "src/CatalogueReview.tsx",
        "src/JobProgress.tsx",
        "src/FindingEvidence.tsx",
        "src/FileInspections.tsx",
        "src/book-workspace.ts",
        "src/return-intent.ts",
        "src/DirectLibrary.tsx",
        "src/PackageComparison.tsx",
        "src/CandidateAssessment.tsx",
        "src/candidate-assessment-api.ts",
        "src/ReviewHistory.tsx",
        "src/CoverReview.tsx",
        "src/CoverPicker.tsx",
        "src/cover-picker-api.ts",
        "src/cover-review-api.ts",
        "src/retired-kinds.ts",
        "src/IdentifierDeclarations.tsx",
        "src/EpubValidation.tsx",
        "src/EpubCheckMessage.tsx",
        "src/epub-validation-api.ts",
        "src/file-inspection-api.ts",
        "src/EvidenceValue.tsx",
        "src/Identity.tsx",
        "src/theme.ts",
        "src/ThemePicker.tsx",
        "src/BrowseView.tsx",
        "src/BookCover.tsx",
        "src/Synopsis.tsx",
        "src/LibraryBookDetails.tsx",
        "src/LibraryBookArt.tsx",
        "src/LibraryBookPane.tsx",
      ],
      thresholds: {
        lines: 80,
        branches: 80,
        functions: 80,
        statements: 80,
        "src/state.ts": {
          lines: 90,
          branches: 90,
          functions: 90,
          statements: 90,
        },
      },
    },
  },
});
