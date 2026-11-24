import React from "react";
import type {
  AuthorEvidence,
  AuthorGroup,
  RecordedSpelling,
} from "./author-groups-api";
import "./author-groups.css";

const unavailable = {
  missing:
    "This snapshot has no recorded alias table. Canonical browsing remains available; alias discovery is unavailable.",
  incompatible:
    "This snapshot's alias table is incompatible. Canonical browsing remains available; alias discovery is unavailable.",
  invalid:
    "This snapshot's author evidence is invalid. Canonical browsing remains available; alias discovery is unavailable.",
};

function Ownership({ spelling }: { spelling: RecordedSpelling }) {
  return spelling.owners > 1 ? (
    <span className="author-collision">
      Shared by {spelling.owners} recorded authors; ambiguous.
    </span>
  ) : null;
}

export function AliasMatches({
  evidence,
  authorId,
}: {
  evidence?: AuthorEvidence;
  authorId?: string;
}) {
  const matches = evidence?.groups
    .filter((group) => !authorId || group.author.id === authorId)
    .filter((group) => group.matched_aliases.length);
  if (!matches?.length) return null;
  return (
    <div className="alias-search-matches">
      {matches.map((group) => (
        <p key={group.author.id}>
          Found by recorded spelling{group.matched_alias_count === 1 ? "" : "s"}
          :{" "}
          {group.matched_aliases.map((match, index) => (
            <React.Fragment key={match.name}>
              {index > 0 && "; "}
              <span>{match.name}</span> <Ownership spelling={match} />
            </React.Fragment>
          ))}
          {group.matched_alias_count > group.matched_aliases.length &&
            `; showing ${group.matched_aliases.length} of ${group.matched_alias_count} matching spellings.`}
          {!authorId && <> · {group.author.name}</>}
        </p>
      ))}
    </div>
  );
}

function Group({ group }: { group: AuthorGroup }) {
  return (
    <div className="recorded-author-group">
      <p>
        <strong>{group.author.name}</strong> · canonical name
      </p>
      {group.canonical_owners > 1 && (
        <p className="author-collision">
          This canonical spelling is shared by {group.canonical_owners} recorded
          authors; ambiguous.
        </p>
      )}
      {group.alias_count ? (
        <>
          <p>
            Recorded aliases
            {group.status === "truncated"
              ? ` · showing ${group.aliases.length} of ${group.alias_count}`
              : ""}
          </p>
          <ul>
            {group.aliases.map((alias) => (
              <li key={alias.name}>
                {alias.name} <Ownership spelling={alias} />
              </li>
            ))}
          </ul>
        </>
      ) : (
        <p>No aliases recorded for this author.</p>
      )}
      {group.status === "truncated" && (
        <p className="author-collision">
          The displayed group is incomplete. Undisplayed spellings cannot
          establish agreement or absence.
        </p>
      )}
    </div>
  );
}

export function AuthorGroups({
  evidence,
  authorId,
}: {
  evidence?: AuthorEvidence;
  authorId?: string;
}) {
  if (!evidence)
    return (
      <p className="context-note">
        Recorded author groups were not supplied by this catalogue response. No
        alias-group conclusion is available.
      </p>
    );
  if (evidence.status !== "available")
    return <p className="context-note">{unavailable[evidence.status]}</p>;
  const groups = evidence.groups.filter(
    (group) => !authorId || group.author.id === authorId,
  );
  if (!groups.length && !evidence.truncated) return null;
  return (
    <details className="author-groups">
      <summary>
        Recorded author names
        {groups.length > 1 ? ` · ${groups.length} groups` : ""}
      </summary>
      <p className="context-note">
        From snapshot {evidence.snapshot.version}. These are recorded name
        groups, not proof of person or file identity. EPUB and library credits
        keep their original spelling. Compare the complete credits, title and
        independent identifiers before drawing a conclusion.
      </p>
      {groups.map((group) => (
        <Group key={group.author.id} group={group} />
      ))}
      {evidence.truncated && (
        <p className="author-collision">
          Only the first 64 relevant author groups are shown. Other groups
          remain unassessed here.
        </p>
      )}
    </details>
  );
}
