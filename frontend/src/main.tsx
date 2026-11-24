import React from "react";
import { createRoot } from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import "@fontsource-variable/literata/wght.css";
import "@fontsource-variable/eb-garamond/wght.css";
import "@fontsource-variable/eb-garamond/wght-italic.css";
import "@fontsource/cinzel/latin-600.css";
import "@fontsource/cinzel-decorative/latin-700.css";
import { applyRoomPrefs } from "./room-prefs";
import "./style.css";
import { App } from "./App";
import { legacyReaderHref } from "./reader/address";

applyRoomPrefs();

// Reading links from the first reader now open the reader page.
const legacy = legacyReaderHref(location.search);
if (legacy) location.replace(legacy);

const client = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: true } },
});

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <QueryClientProvider client={client}>
      {legacy ? null : <App />}
    </QueryClientProvider>
  </React.StrictMode>,
);
