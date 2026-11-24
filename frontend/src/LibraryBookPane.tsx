import React, { useState } from "react";
import { LibraryBookArt } from "./LibraryBookArt";
import { type Cover } from "./BookCover";
import { type BookDetails } from "./LibraryBookDetails";
import { Synopsis } from "./Synopsis";
import { CatalogueReview } from "./CatalogueReview";
import { CatalogueSupport } from "./CatalogueSupport";
import { SeriesName } from "./SeriesName";
import {
  checkLabel,
  dateLabel,
  matchLabels,
  positionLabel,
  preferredMembership,
  savedMatch,
  type CataloguePin,
  type LibraryListing,
  type LibraryWork,
} from "./Library";

function CopyEvidence({ work }: { work: LibraryWork }) {
  return (
    <div className="library-proof">
      {work.copies.length > 0 && (
        <>
          <h3>Calibre copies</h3>
          <ul>
            {work.copies.map((copy) => (
              <li key={copy.calibre_id}>
                <span>{copy.title}</span>
                <span className="context-note">
                  {" · "}
                  Calibre #{copy.calibre_id}
                  {copy.last_known
                    ? " · last known copy"
                    : " · matched at check time"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {work.contained_in.length > 0 && (
        <>
          <h3>In collections</h3>
          <ul>
            {work.contained_in.map((copy) => (
              <li key={copy.calibre_id}>
                <span>{copy.title}</span>
                <span className="context-note">
                  {" · "}
                  Calibre #{copy.calibre_id}
                  {copy.last_known
                    ? " · last known copy"
                    : " · matched at check time"}
                </span>
              </li>
            ))}
          </ul>
        </>
      )}
      {work.candidates.length > 0 && (
        <>
          <h3>Incoming · needs review</h3>
          <ul>
            {work.candidates.map((candidate, index) => (
              <li key={index}>
                {candidate.title} ·{" "}
                {candidate.stage === "inbox" ? "Inbox" : "Shelve"} ·{" "}
                {candidate.confidence === "possible"
                  ? "possible match"
                  : "saved identification"}
              </li>
            ))}
          </ul>
        </>
      )}
      {work.state === "unknown" && <p>Not confirmed either way.</p>}
      {work.state === "missing" && (
        <p>The complete check found no Calibre copy.</p>
      )}
    </div>
  );
}

export function LibraryBookPane({
  work,
  book,
  data,
  art,
  seriesId,
  pin,
  catalogueMismatch = false,
  follow,
  href,
  back,
}: {
  work: LibraryWork;
  book?: BookDetails;
  data: LibraryListing;
  art?: Cover;
  seriesId?: string | null;
  pin?: CataloguePin;
  catalogueMismatch?: boolean;
  follow: (
    event: React.MouseEvent<HTMLAnchorElement>,
    work: string,
    selection: { cw?: string; cs?: string },
  ) => void;
  href: (selection: { cw?: string; cs?: string }) => string;
  back: () => void;
}) {
  const [review, setReview] = useState(false);
  const positioned = {
    ...work,
    authors: book?.authors
      ? [...new Set(book.authors.map((author) => author.name))]
      : work.authors,
    series:
      data.shelves && seriesId === null
        ? []
        : book?.series?.length
          ? book.series.map((series) => ({
              ...work.series.find((member) => member.id === series.id),
              ...series,
              lead_work_id:
                series.lead_work_id ??
                work.series.find((member) => member.id === series.id)
                  ?.lead_work_id,
            }))
          : work.series,
  };
  const membership = preferredMembership(positioned, seriesId);
  const copies = [...work.copies, ...work.contained_in];
  const [firstCopy] = copies;
  const canReview = !!pin?.version && !!pin.sha256;
  const copyUrl =
    data.finish_origin &&
    /^https?:\/\/[^/?#]+\/?$/.test(data.finish_origin) &&
    firstCopy
      ? `${data.finish_origin.replace(/\/$/, "")}/book?calibre=${firstCopy.calibre_id}`
      : null;
  const editions = book?.editions ?? [];
  const editionCount = book?.edition_count;
  const published = book?.first_published ?? work.first_published;
  const publishedYear = published?.match(/^\d{4}/)?.[0] ?? published;
  return (
    <>
      <button className="back library-back" onClick={back}>
        Back to library
      </button>
      <div className="folio library-detail-folio">
        <div className="reading-book-top">
          <LibraryBookArt
            work={positioned}
            cover={book?.cover ?? art}
            seriesId={seriesId}
            prominent
          />
          <div>
            <h2 id="selected-book" className="work-title" tabIndex={-1}>
              {work.title}
            </h2>
            <p className="author">
              {positioned.authors.join(", ") || "Author not recorded"}
            </p>
            <p className="book-bibliography">
              {membership ? (
                <>
                  <SeriesName name={membership.name} />
                  {" · "}
                  {positionLabel(positioned, seriesId)}
                  <br />
                </>
              ) : (
                <>
                  Standalone and collected
                  <br />
                </>
              )}
              {work.kind
                .replaceAll("_", " ")
                .replace(/^./, (letter) => letter.toUpperCase())}
              {publishedYear && ` · first published ${publishedYear}`}
              {editionCount != null &&
                ` · ${editionCount} ${editionCount === 1 ? "edition" : "editions"}`}
            </p>
          </div>
        </div>
        <div className={`library-status-well ${work.state}`}>
          <strong>
            <span className="status-dot" />
            {matchLabels[work.state]}
            {savedMatch(work) && " · saved match"}
          </strong>
          <span>
            {firstCopy
              ? `Calibre copy ${firstCopy.calibre_id}${firstCopy.last_known || !work.current ? ", last known" : ", matched at check time"} · `
              : ""}
            {checkLabel(data.coverage)}, {dateLabel(data.checked_at)}
          </span>
          {savedMatch(work) && (
            <span>Not yet re-confirmed by a complete check.</span>
          )}
          {work.state === "unknown" && <span>Not confirmed either way.</span>}
        </div>
        {book?.synopsis?.trim() ? (
          <Synopsis text={book.synopsis} headingLevel={3} readingRoom />
        ) : (
          book && <p className="context-note">No synopsis recorded</p>
        )}
        <div className="reading-book-actions">
          {canReview && (
            <button
              className="secondary"
              aria-expanded={review}
              onClick={() => setReview((value) => !value)}
            >
              Review metadata
            </button>
          )}
          {copyUrl && (
            <a href={copyUrl} target="_blank" rel="noreferrer">
              Open in Library Finish ↗
            </a>
          )}
        </div>
        {review && canReview && (
          <CatalogueReview
            workId={work.id}
            title={work.title}
            version={pin!.version!}
            sha256={pin!.sha256!}
            fixture={false}
          />
        )}
        <div className="reading-disclosures">
          <details>
            <summary>
              <span>Editions</span>
              <small>{editionCount ?? "Unavailable"}</small>
            </summary>
            {editions.length ? (
              <>
                <ul className="editions">
                  {editions.map((edition) => (
                    <li key={edition.id}>
                      <strong>{edition.format || "Format not recorded"}</strong>
                      <span>{edition.release_date || "Date not recorded"}</span>
                      <small>
                        {edition.publisher || "Publisher not recorded"}
                      </small>
                      <small>
                        {edition.isbn13 ||
                          edition.isbn10 ||
                          "ISBN not recorded"}
                      </small>
                    </li>
                  ))}
                </ul>
                {(editionCount ?? 0) > editions.length && (
                  <p className="context-note">First {editions.length} shown</p>
                )}
              </>
            ) : (
              <p>{book ? "None recorded" : "Catalogue editions unavailable"}</p>
            )}
          </details>
          <details>
            <summary>
              <span>Library evidence</span>
              <small>
                {copies.length} {copies.length === 1 ? "copy" : "copies"} ·
                check date · coverage
              </small>
            </summary>
            <p className="context-note">
              {checkLabel(data.coverage)} · {dateLabel(data.checked_at)}
              {!work.current && " · current copy unconfirmed"}
            </p>
            <CopyEvidence work={work} />
          </details>
          <details>
            <summary>
              <span>Record details</span>
              <small>
                snapshot {data.catalogue_version ?? "unavailable"} · identifiers
              </small>
            </summary>
            <dl className="provenance">
              <dt>Source</dt>
              <dd>Library Finish</dd>
              <dt>Work</dt>
              <dd className="source-id">{work.id}</dd>
              {published && (
                <>
                  <dt>First published</dt>
                  <dd>{published}</dd>
                </>
              )}
              <dt>Check token</dt>
              <dd className="source-id">{data.snapshot}</dd>
              {pin?.sha256 && (
                <>
                  <dt>Catalogue fingerprint</dt>
                  <dd className="source-id">{pin.sha256}</dd>
                </>
              )}
            </dl>
            {canReview ? (
              <>
                <a
                  className="library-evidence-link"
                  href={href({ cw: work.id })}
                  onClick={(event) => follow(event, work.id, { cw: work.id })}
                >
                  Catalogue evidence
                </a>
                <ul className="series-links">
                  {work.series.map((series) => (
                    <li key={series.id}>
                      <a
                        href={href({ cs: String(series.id) })}
                        onClick={(event) =>
                          follow(event, work.id, { cs: String(series.id) })
                        }
                        aria-label={`Browse ${series.name} in catalogue`}
                      >
                        <SeriesName name={series.name} />
                      </a>
                    </li>
                  ))}
                </ul>
              </>
            ) : (
              <p className="context-note">
                {catalogueMismatch
                  ? "Library check uses a different catalogue version."
                  : "Catalogue unavailable"}
              </p>
            )}
            {book ? (
              <CatalogueSupport records={book.support ?? []} />
            ) : (
              <p>Catalogue support unavailable</p>
            )}
          </details>
        </div>
      </div>
    </>
  );
}
