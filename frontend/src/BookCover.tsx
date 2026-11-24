import React, { useState } from "react";

export type Cover = {
  url: string;
  sha256: string;
  width: number;
  height: number;
  media_type: string;
  source_url?: string;
};

export function BookCover({
  cover,
  prominent = false,
  fallback = null,
}: {
  cover?: Cover | null;
  prominent?: boolean;
  fallback?: React.ReactNode;
}) {
  const [failed, setFailed] = useState<string | null>(null);
  if (
    !cover ||
    failed === cover.url ||
    !cover.url.startsWith("/api/catalogue/covers/") ||
    cover.url.includes("\\")
  )
    return <>{fallback}</>;
  return (
    <img
      className="book-cover"
      src={cover.url}
      alt=""
      width={cover.width}
      height={cover.height}
      loading={prominent ? "eager" : "lazy"}
      decoding="async"
      onError={() => setFailed(cover.url)}
    />
  );
}
