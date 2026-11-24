import React from "react";
import family from "./assets/librarium-symbols.svg";

export function ArchivistMark({
  className = "",
  variant = "emblem",
}: {
  className?: string;
  variant?: "emblem" | "small";
}) {
  return (
    <svg
      className={`archivist-mark ${className}`}
      viewBox="0 0 1000 1000"
      width="256"
      height="256"
      aria-hidden="true"
      focusable="false"
    >
      <use href={`${family}#${variant}`} width="1000" height="1000" />
    </svg>
  );
}

export function LibrariumWordmark() {
  return (
    <svg
      className="wordmark"
      viewBox="0 0 1060 320"
      width="1060"
      height="320"
      role="img"
      aria-label="Librarium"
      focusable="false"
    >
      <use href={`${family}#wordmark`} width="1060" height="320" />
    </svg>
  );
}
