import React from "react";
import { useQuery } from "@tanstack/react-query";
import { api } from "./api";
import { Synopsis } from "./Synopsis";

type Props = {
  workId: string;
  version: string;
  sha256: string;
  enabled: boolean;
  renderBook?: (book?: BookDetails) => React.ReactNode;
};

export type BookDetails = {
  id: string;
  authors?: { id: string; name: string }[];
  series?: import("./Library").LibraryWork["series"];
  synopsis?: string | null;
  first_published?: string | null;
  edition_count?: number;
  cover?: import("./BookCover").Cover | null;
  editions?: {
    id: string;
    format?: string | null;
    release_date?: string | null;
    publisher?: string | null;
    isbn13?: string | null;
    isbn10?: string | null;
  }[];
  support?: {
    field: string;
    value: string | null;
    agree: string[];
    disagree: { origin: string; value: unknown }[];
  }[];
  snapshot: { version: string; sha256: string; fixture: false };
};

function matchesPin(
  value: unknown,
  { workId, version, sha256 }: Props,
): value is BookDetails {
  if (!value || typeof value !== "object") return false;
  const data = value as Partial<BookDetails>;
  return (
    data.id === workId &&
    data.snapshot?.version === version &&
    data.snapshot?.sha256 === sha256 &&
    data.snapshot?.fixture === false &&
    (data.synopsis == null || typeof data.synopsis === "string")
  );
}

export function LibraryBookDetails(props: Props) {
  const { workId, version, sha256, enabled } = props;
  const pinned = !!workId && !!version && !!sha256;
  const queryKey = ["library-book-details", workId, version, sha256];
  const query = useQuery({
    queryKey,
    queryFn: async ({ signal }) => {
      const data = await api<unknown>(
        `catalogue/works/${encodeURIComponent(workId)}?${new URLSearchParams({ version, sha256 })}`,
        { signal },
      );
      if (!matchesPin(data, props)) throw new Error("Synopsis pin mismatch");
      return data;
    },
    enabled: enabled && pinned,
    retry: false,
    staleTime: Infinity,
  });

  if (!enabled) return null;
  const data = matchesPin(query.data, props) ? query.data : undefined;
  if (props.renderBook)
    return (
      <>
        {props.renderBook(data)}
        {!pinned || query.isError ? (
          <p className="error" role="status">
            Book context unavailable.
            {pinned && (
              <button onClick={() => void query.refetch()}>
                Retry book context
              </button>
            )}
          </p>
        ) : (
          query.isPending && <p role="status">Loading book context…</p>
        )}
      </>
    );
  return (
    <div className="library-book-details">
      {!pinned || query.isError || (!query.isPending && !data) ? (
        <>
          <p role="status">Synopsis unavailable</p>
          {pinned && (
            <button
              type="button"
              disabled={query.isFetching}
              onClick={() => void query.refetch()}
            >
              Retry synopsis
            </button>
          )}
        </>
      ) : query.isPending ? (
        <p role="status">Loading synopsis…</p>
      ) : data?.synopsis?.trim() ? (
        <Synopsis
          key={JSON.stringify(queryKey)}
          text={data.synopsis}
          headingLevel={2}
        />
      ) : (
        <p className="context-note">No synopsis recorded</p>
      )}
    </div>
  );
}
