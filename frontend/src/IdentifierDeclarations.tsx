import React, { useId } from "react";
import type { EpubReport, IdentifierAssociation } from "./types";
import {
  capturesIdentifierEvidence,
  identifierEvidenceBinds,
} from "./file-inspection-api";
import "./identifier-declarations.css";

export const identifierAssociationLabels: Record<
  IdentifierAssociation,
  string
> = {
  identifier: "Identifier target",
  other: "Other package element",
  ambiguous: "Ambiguous target",
  unresolved: "Unresolved target",
  unsupported: "Unsupported reference",
};
export function RawDeclarationValue({ value }: { value: string | null }) {
  return (
    <bdi>{value === null ? "Not present" : value === "" ? "Empty" : value}</bdi>
  );
}
export function IdentifierDeclarations({ report }: { report: EpubReport }) {
  const id = useId();
  const evidence = report.identifier_evidence;
  const captures = capturesIdentifierEvidence(report.policy?.version);
  let note = "";
  if (!captures)
    note =
      "Not recorded by this inspection. A new inspection must be explicitly requested to capture identifier declarations.";
  else if (!identifierEvidenceBinds(report))
    note =
      "Identifier declarations could not be verified against this package report.";
  else if (!evidence)
    note =
      "Unavailable from this incomplete inspection. The absence of declarations has not been established.";
  return (
    <section
      className="report-part identifier-declarations"
      aria-labelledby={`${id}-heading`}
    >
      <h4 id={`${id}-heading`}>Identifier declarations</h4>
      {note ? (
        <p>{note}</p>
      ) : (
        evidence && (
          <>
            <p className="identifier-intro">
              Raw package declarations and their recorded targets. These
              observations do not establish identifier validity, content
              identity or readiness.
            </p>
            <dl className="identifier-fields">
              <div>
                <dt>Package unique-identifier pointer</dt>
                <dd>
                  <RawDeclarationValue value={evidence.unique_identifier} />
                </dd>
              </div>
              <div>
                <dt>Package prefix declarations</dt>
                <dd>
                  <RawDeclarationValue value={evidence.prefix} />
                </dd>
              </div>
            </dl>
            {!evidence.entries.length && !evidence.refinements.length ? (
              <p>
                No identifier declarations or type records were captured in this
                package.
              </p>
            ) : (
              <p>
                {evidence.entries.length.toLocaleString()} identifier{" "}
                {evidence.entries.length === 1 ? "declaration" : "declarations"}
                ; {evidence.refinements.length.toLocaleString()} type{" "}
                {evidence.refinements.length === 1 ? "record" : "records"}.
                Source indexes are zero-based positions in the package XML.
              </p>
            )}
            <ol className="identifier-entries">
              {evidence.entries.map((entry) => (
                <li key={entry.source_index}>
                  <p className="identifier-value">
                    <RawDeclarationValue value={entry.value} />
                  </p>
                  <p className="context-note">
                    Package source index {entry.source_index}
                  </p>
                  <dl className="identifier-fields">
                    <div>
                      <dt>id</dt>
                      <dd>
                        <RawDeclarationValue value={entry.id} />
                      </dd>
                    </div>
                    <div>
                      <dt>xml:id</dt>
                      <dd>
                        <RawDeclarationValue value={entry.xml_id} />
                      </dd>
                    </div>
                    <div>
                      <dt>opf:scheme</dt>
                      <dd>
                        <RawDeclarationValue value={entry.opf_scheme} />
                      </dd>
                    </div>
                    <div>
                      <dt>Package occurrences of each value</dt>
                      <dd>
                        id: {entry.id_count}; xml:id: {entry.xml_id_count}
                      </dd>
                    </div>
                  </dl>
                  {!entry.text_only && (
                    <p className="context-note">
                      Contains nested markup; the recorded text is not a plain
                      identifier declaration.
                    </p>
                  )}
                </li>
              ))}
            </ol>
            {evidence.refinements.length > 0 && (
              <details className="identifier-refinements">
                <summary>
                  Type records and refinement targets (
                  {evidence.refinements.length.toLocaleString()})
                </summary>
                <ol>
                  {evidence.refinements.map((entry) => (
                    <li key={entry.source_index}>
                      <p>
                        <strong>
                          {identifierAssociationLabels[entry.association]}
                        </strong>{" "}
                        · package source index {entry.source_index}
                      </p>
                      <dl className="identifier-fields">
                        <div>
                          <dt>Property</dt>
                          <dd>
                            <RawDeclarationValue value={entry.property} />
                          </dd>
                        </div>
                        <div>
                          <dt>Recorded value</dt>
                          <dd>
                            <RawDeclarationValue value={entry.value} />
                          </dd>
                        </div>
                        <div>
                          <dt>refines</dt>
                          <dd>
                            <RawDeclarationValue value={entry.refines} />
                          </dd>
                        </div>
                        <div>
                          <dt>scheme</dt>
                          <dd>
                            <RawDeclarationValue value={entry.scheme} />
                          </dd>
                        </div>
                        <div>
                          <dt>Target ID</dt>
                          <dd>
                            <RawDeclarationValue value={entry.target_id} />
                          </dd>
                        </div>
                        <div>
                          <dt>Target occurrences</dt>
                          <dd>{entry.target_count}</dd>
                        </div>
                        <div>
                          <dt>Target source index</dt>
                          <dd>{entry.target_source_index ?? "Not recorded"}</dd>
                        </div>
                      </dl>
                      {!entry.text_only && (
                        <p className="context-note">Contains nested markup.</p>
                      )}
                    </li>
                  ))}
                </ol>
              </details>
            )}
            <details className="identifier-provenance">
              <summary>Identifier capture provenance</summary>
              <dl className="identifier-fields">
                <div>
                  <dt>Schema</dt>
                  <dd>{evidence.schema_version}</dd>
                </div>
                <div>
                  <dt>Package document</dt>
                  <dd>{evidence.package_path}</dd>
                </div>
                <div>
                  <dt>Package byte digest</dt>
                  <dd>{evidence.package_sha256}</dd>
                </div>
                <div>
                  <dt>EPUB version</dt>
                  <dd>{evidence.package_version}</dd>
                </div>
              </dl>
            </details>
          </>
        )
      )}
    </section>
  );
}
