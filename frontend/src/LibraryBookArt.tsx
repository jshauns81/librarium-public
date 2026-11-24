import React from "react";
import { BookCover, type Cover } from "./BookCover";
import type { LibraryWork } from "./Library";
import { preferredMembership } from "./Library";

export function LibraryBookArt({
  work,
  cover,
  seriesId,
  prominent = false,
}: {
  work: LibraryWork;
  cover?: Cover | null;
  seriesId?: string | null;
  prominent?: boolean;
}) {
  if (!cover) return null;
  const membership = preferredMembership(work, seriesId);
  const position = membership?.position;
  return (
    <span className="shelf-art" aria-hidden="true">
      <BookCover cover={cover} prominent={prominent} />
      {position != null && position !== 0 && (
        <span className="position-badge">{position}</span>
      )}
    </span>
  );
}
