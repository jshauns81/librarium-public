import React, { useId } from "react";
import type { EpubReport } from "./types";
import {
  capturesSourceAttribution,
  sourceAttributionBinds,
} from "./file-inspection-api";

export function SourceAttribution({ report }: { report: EpubReport }) {
  const id = useId();
  const evidence = report.source_attribution;
  const recorded = capturesSourceAttribution(report.policy?.version);
  const valid = sourceAttributionBinds(report);
  return (
    <section
      className="report-part source-attribution"
      aria-labelledby={`${id}-heading`}
    >
      <h4 id={`${id}-heading`}>Source title and credits</h4>
      {!recorded ? (
        <p>
          Not recorded by this inspection. Request a new inspection to capture
          source title and credit labels.
        </p>
      ) : !valid ? (
        <p>
          Source title and credit evidence could not be bound to this report.
        </p>
      ) : evidence?.status !== "recorded" || !evidence.observations.length ? (
        <p>
          No eligible title and credit block was captured. Whole-file identity
          remains unconfirmed.
        </p>
      ) : (
        <>
          <p>
            Short labels from the EPUB source. Whole-file identity remains
            unconfirmed; these labels do not establish narrative completeness or
            rendered visibility.
          </p>
          <ol className="contents-items">
            {evidence.observations.map((entry) => (
              <li key={entry.id}>
                <p>
                  <strong>
                    {entry.rule === "semantic_titlepage"
                      ? "Marked title page"
                      : "Unclassified front matter"}
                  </strong>
                </p>
                {entry.title && (
                  <p>
                    <bdi>{entry.title.text}</bdi>
                    <span className="contents-context">
                      {" "}
                      · Source element {entry.title.source_index}
                    </span>
                  </p>
                )}
                {entry.credits.map((credit) => (
                  <p key={credit.source_index}>
                    <bdi>{credit.text}</bdi>
                    <span className="contents-context">
                      {" "}
                      · Source element {credit.source_index}
                    </span>
                  </p>
                ))}
                <p className="contents-target">
                  <bdi>{entry.path}</bdi> · Reading-order position{" "}
                  {entry.spine_index + 1}
                </p>
                <details>
                  <summary>Source observation details</summary>
                  <dl>
                    <dt>Observation</dt>
                    <dd>{entry.id}</dd>
                    <dt>Block source element</dt>
                    <dd>{entry.source_index} (zero-based)</dd>
                    <dt>Capture rule</dt>
                    <dd>{entry.rule}</dd>
                    <dt>Resource digest</dt>
                    <dd className="contents-target">{entry.resource_sha256}</dd>
                  </dl>
                </details>
              </li>
            ))}
          </ol>
        </>
      )}
    </section>
  );
}
