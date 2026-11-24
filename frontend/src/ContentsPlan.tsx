import React from "react";
import type {
  EpubContentsPlan,
  EpubContentsPlanEntry,
  EpubContentsPlanSummary,
} from "./types";
import "./contents-plan.css";

const reasons: Record<string, string> = {
  existing_navigation_sound:
    "Recorded navigation has supported source targets.",
  complete_numbered_headings:
    "The recorded chapter numbers form a continuous sequence.",
  printed_chapter_targets: "Printed contents links provide source targets.",
  inspection_incomplete: "The structural inspection did not finish.",
  source_evidence_unavailable:
    "The source positions needed for planning were not recorded.",
  structural_failure:
    "Structural findings need review before contents can be planned.",
  invalid_target:
    "A contents target could not be supported by the recorded source.",
  duplicate_target: "More than one entry points to the same source position.",
  target_order: "Contents targets do not follow the recorded reading order.",
  navigation_conflict: "Recorded navigation sources disagree.",
  ambiguous_numbering: "Recorded chapter numbering is ambiguous.",
  unassigned_chapters:
    "Some recorded chapters could not be placed in this plan.",
  unsupported_structure:
    "The recorded structure is outside this planner's supported cases.",
  output_limit: "The plan exceeded its output budget.",
  hierarchy_limit: "The contents hierarchy exceeded the planning limit.",
  empty_duplicate_stub:
    "A duplicate title stub is omitted from the proposed navigation.",
  empty_title_holder:
    "A title holder without recorded body text is omitted from the proposed navigation.",
  // Contents plan v2: Library Finish's contents rules (L061).
  contents_evidence_unavailable:
    "The short lines the contents rules read were not recorded for this book.",
  existing_matches_headings:
    "The book's own contents list already matches its chapter headings.",
  existing_matches_rebuild:
    "A rebuilt list would be the same as the book's own list.",
  rebuild_far_shorter:
    "The rebuild found far fewer entries than the book's own list, so the list is kept.",
  rebuild_too_short:
    "The rebuild found too few entries; the book's own clean list is kept.",
  no_usable_headings:
    "No usable chapter headings were found; the book's own clean list is kept.",
  chapter_headings: "Rebuilt from the book's chapter headings.",
  printed_contents:
    "Rebuilt from the links on the book's printed contents page.",
  single_story:
    "A short book without chapter headings: one entry for the story, named by its title.",
  no_chapter_headings: "No chapter headings were found in this long book.",
  too_few_headings: "Too few chapter headings were found for this long book.",
  unlinkable_headings:
    "Chapter headings were found, but too few of them can be linked.",
  too_few_entries:
    "Chapter headings were found, but the rebuilt list would have too few entries.",
  numbering_unsettled:
    "The chapter numbering has gaps or repeats the rules cannot settle.",
  missed_chapters:
    "One entry would hold far too many words: the rules missed its chapters.",
  ocr_scan: "This is an automatic OCR scan; a better copy is needed.",
};

const origins: Record<string, string> = {
  heading: "Source heading",
  printed_link: "Printed contents link",
  printed_group: "Printed contents group",
  paragraph: "Styled chapter line",
  joined_label: "Heading joined with its subtitle",
  split_heading: "Split from a book and chapter heading",
  numbered_book: "Numbered book grouping its restarting chapters",
  book_title: "Book title for the whole story",
};

const PLAN_POLICIES = [
  "librarium.contents-plan.v1",
  "librarium.contents-plan.v2",
];

const measureNames: [
  keyof NonNullable<EpubContentsPlan["measures"]>,
  string,
][] = [
  ["existing", "Entries in the book's own list"],
  ["headings", "Chapter headings found"],
  ["linked", "Headings that can be linked"],
  ["entries", "Entries in the rebuilt list"],
  ["words", "Words in the reading order"],
];

function reasonText(code: string): string {
  return Object.hasOwn(reasons, code)
    ? reasons[code]
    : `Recorded reason: ${code}`;
}

function target(path: string, fragment: string | null): string {
  return path + (fragment === null ? "" : `#${fragment}`);
}

function entryLabel(label: string): string {
  return label || "Unlabelled";
}

export function ContentsPlanStatus({
  summary,
  showHeading = true,
}: {
  summary?: EpubContentsPlanSummary;
  showHeading?: boolean;
}) {
  if (!summary) return null;
  const known =
    PLAN_POLICIES.includes(summary.policy_version) &&
    ["keep", "propose", "held"].includes(summary.decision) &&
    Array.isArray(summary.reason_codes);
  return (
    <div
      className="contents-plan-status"
      role="group"
      aria-label="Contents planning"
    >
      {showHeading && <h4>Contents planning</h4>}
      <p
        className={`plan-disposition${!known ? " plan-unavailable" : summary.decision === "held" ? " plan-held" : ""}`}
      >
        {!known
          ? "Plan unavailable"
          : summary.decision === "keep"
            ? "Keep recorded navigation"
            : summary.decision === "propose"
              ? "Changes proposed"
              : "Planning held"}
      </p>
      {known &&
        (summary.reason_codes.length > 0 ? (
          <ul className="plan-reasons" aria-label="Plan reasons">
            {summary.reason_codes.map((code, index) => (
              <li key={index}>{reasonText(code)}</li>
            ))}
          </ul>
        ) : (
          <p>No planning reason was recorded.</p>
        ))}
    </div>
  );
}

function flatten(entries: EpubContentsPlanEntry[]) {
  const output: { entry: EpubContentsPlanEntry; ancestors: string[] }[] = [];
  const pending = entries
    .map((entry) => ({ entry, ancestors: [] as string[] }))
    .reverse();
  while (pending.length) {
    const item = pending.pop()!;
    output.push(item);
    const ancestors = [...item.ancestors, entryLabel(item.entry.label)];
    for (const entry of [...item.entry.children].reverse()) {
      pending.push({ entry, ancestors });
    }
  }
  return output;
}

function SourceDetails({ entry }: { entry: EpubContentsPlanEntry }) {
  return (
    <details className="plan-source">
      <summary
        aria-label={`Source details for ${entryLabel(entry.label)} in ${entry.path}`}
      >
        Source details
      </summary>
      <dl className="provenance">
        <dt>Origin</dt>
        <dd>
          {Object.hasOwn(origins, entry.origin)
            ? origins[entry.origin]
            : entry.origin}
        </dd>
        <dt>Target document index</dt>
        <dd>{entry.position.document_index.toLocaleString()}</dd>
        <dt>Target source index</dt>
        <dd>{entry.position.source_index.toLocaleString()}</dd>
        <dt>Target word offset</dt>
        <dd>{entry.position.word_offset.toLocaleString()}</dd>
        <dt>Target document digest</dt>
        <dd className="hash">{entry.position.document_sha256}</dd>
        <dt>Label source</dt>
        <dd>{entry.label_source.path}</dd>
        <dt>Label source index</dt>
        <dd>{entry.label_source.source_index.toLocaleString()}</dd>
        <dt>Label document digest</dt>
        <dd className="hash">{entry.label_source.document_sha256}</dd>
      </dl>
    </details>
  );
}

export function ContentsPlan({
  plan,
  sourceSha256,
  inspectionPolicy,
}: {
  plan?: EpubContentsPlan | null;
  sourceSha256: string;
  inspectionPolicy?: string;
}) {
  const known =
    plan &&
    PLAN_POLICIES.includes(plan.policy_version) &&
    plan.source_sha256 === sourceSha256 &&
    plan.inspection_policy === inspectionPolicy &&
    plan.ready === false &&
    ["keep", "propose", "held"].includes(plan.decision) &&
    Array.isArray(plan.existing) &&
    Array.isArray(plan.entries) &&
    Array.isArray(plan.reason_codes) &&
    Array.isArray(plan.excluded_targets) &&
    Array.isArray(plan.limitations) &&
    (plan.decision === "propose"
      ? plan.entries.length > 0
      : plan.entries.length === 0) &&
    (plan.decision !== "keep" || plan.existing.length > 0) &&
    (plan.problems === undefined ||
      (Array.isArray(plan.problems) &&
        plan.problems.every((problem) => typeof problem === "string"))) &&
    (plan.measures == null ||
      measureNames.every(([name]) => Number.isInteger(plan.measures?.[name])));

  if (!plan || !known) {
    return (
      <section
        className="report-part contents-plan"
        aria-labelledby="contents-plan-heading"
      >
        <h4 id="contents-plan-heading">Contents plan</h4>
        {!plan ? (
          <>
            <p className="plan-disposition plan-unrecorded">
              Not recorded by this inspection
            </p>
            <p>Start a new inspection to capture a contents plan.</p>
          </>
        ) : (
          <>
            <p className="plan-disposition plan-unavailable">
              Plan unavailable
            </p>
            <p>
              The recorded plan could not be verified against this report's
              source and supported policy.
            </p>
          </>
        )}
      </section>
    );
  }

  const proposed = plan.decision === "propose" ? flatten(plan.entries) : [];
  return (
    <section
      className="report-part contents-plan"
      aria-labelledby="contents-plan-heading"
    >
      <h4 id="contents-plan-heading">Contents plan</h4>
      <ContentsPlanStatus summary={plan} showHeading={false} />
      <p className="context-note">
        This plan is read-only. The EPUB is unchanged.
      </p>
      {plan.decision === "held" && (
        <p>No replacement list is proposed while planning is held.</p>
      )}
      {plan.decision === "keep" && <p>No navigation changes proposed.</p>}
      {plan.problems && plan.problems.length > 0 && (
        <div className="plan-problems">
          <h5>What the rules found</h5>
          <ul aria-label="Rule findings">
            {plan.problems.map((problem, index) => (
              <li key={index}>{problem}</li>
            ))}
          </ul>
        </div>
      )}
      <div className="plan-columns">
        <div>
          <h5>Recorded navigation</h5>
          {plan.existing.length > 0 ? (
            <ol className="plan-entries" aria-label="Recorded navigation">
              {plan.existing.map((entry, index) => (
                <li key={index}>
                  <span className="plan-entry-label">
                    {entryLabel(entry.label)}
                  </span>
                  <span className="plan-entry-target">
                    {target(entry.path, entry.fragment)}
                  </span>
                  {entry.ancestors.length > 0 && (
                    <span className="plan-entry-context">
                      Within: {entry.ancestors.map(entryLabel).join(" / ")}
                    </span>
                  )}
                  <span className="plan-entry-context">
                    {entry.kind === "nav"
                      ? "NAV"
                      : entry.kind === "ncx"
                        ? "NCX"
                        : entry.kind}
                  </span>
                </li>
              ))}
            </ol>
          ) : (
            <p>No navigation was recorded in this plan.</p>
          )}
        </div>
        {plan.decision === "propose" && (
          <div>
            <h5>Proposed navigation</h5>
            <ol className="plan-entries" aria-label="Proposed navigation">
              {proposed.map(({ entry, ancestors }, index) => (
                <li key={index}>
                  <span className="plan-entry-label">
                    {entryLabel(entry.label)}
                  </span>
                  {ancestors.length > 0 && (
                    <span className="plan-entry-context">
                      Within: {ancestors.join(" / ")}
                    </span>
                  )}
                  <span className="plan-entry-target">
                    {target(entry.path, entry.fragment)}
                  </span>
                  <span className="plan-entry-context">
                    {entry.requires_anchor
                      ? "New anchor required"
                      : entry.fragment === null
                        ? "Document start"
                        : "Existing source anchor"}
                  </span>
                  <SourceDetails entry={entry} />
                </li>
              ))}
            </ol>
          </div>
        )}
      </div>
      {plan.excluded_targets.length > 0 && (
        <details className="plan-exclusions">
          <summary>
            Excluded targets ({plan.excluded_targets.length.toLocaleString()})
          </summary>
          <p>
            These targets are excluded from the proposal. Source documents are
            unchanged.
          </p>
          <ul className="plan-entries">
            {plan.excluded_targets.map((entry, index) => (
              <li key={index}>
                <span className="plan-entry-target">
                  {target(entry.path, entry.fragment)}
                </span>
                <span>{reasonText(entry.reason)}</span>
              </li>
            ))}
          </ul>
        </details>
      )}
      {plan.limitations.length > 0 && (
        <div className="plan-scope">
          <h5>Scope</h5>
          <ul>
            {plan.limitations.map((limitation, index) => (
              <li key={index}>{limitation}</li>
            ))}
          </ul>
        </div>
      )}
      <details className="plan-provenance">
        <summary>Plan provenance</summary>
        <dl className="provenance">
          <dt>Planner policy</dt>
          <dd>{plan.policy_version}</dd>
          {plan.measures &&
            measureNames.map(([name, label]) => (
              <React.Fragment key={name}>
                <dt>{label}</dt>
                <dd>{plan.measures![name].toLocaleString()}</dd>
              </React.Fragment>
            ))}
          <dt>Inspection policy</dt>
          <dd>{plan.inspection_policy}</dd>
          <dt>Preserved source digest</dt>
          <dd className="hash">{plan.source_sha256}</dd>
        </dl>
      </details>
    </section>
  );
}
