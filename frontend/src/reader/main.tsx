import React from "react";
import { createRoot } from "react-dom/client";
import "@fontsource-variable/eb-garamond/wght.css";
import "@fontsource-variable/eb-garamond/wght-italic.css";
import "@fontsource/cinzel/latin-500.css";
import "./reader.css";
import { ReaderApp } from "./ReaderApp";
import { readerAddress } from "./address";

const address = readerAddress(location.pathname, location.search);

createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    {address ? (
      <ReaderApp bookId={address.bookId} inventory={address.inventory} />
    ) : (
      <p className="reader-lost">
        This reading link is incomplete. <a href="/">Return to the library</a>{" "}
        and open the book again.
      </p>
    )}
  </React.StrictMode>,
);
