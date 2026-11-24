import React, { useId, useState } from "react";
import { EvidenceValue } from "./EvidenceValue";
import "./catalogue-support.css";

export type CatalogueSupportRecord = {
  field: string;
  value: unknown;
  agree: string[];
  disagree: { origin: string; value: unknown }[];
};

type RecordedValue = { key: string; value: unknown; sources: Set<string> };
type OtherValue = { origin: string; value: unknown; against: Set<string> };
type FieldGroup = {
  field: string;
  recorded: Map<string, RecordedValue>;
  other: Map<string, OtherValue>;
};

function valueKey(value: unknown) {
  return `${typeof value}:${JSON.stringify(value)}`;
}

function groupFields(records: CatalogueSupportRecord[]) {
  const groups = new Map<string, FieldGroup>();
  for (const record of records) {
    let group = groups.get(record.field);
    if (!group) {
      group = { field: record.field, recorded: new Map(), other: new Map() };
      groups.set(record.field, group);
    }
    const key = valueKey(record.value);
    let recorded = group.recorded.get(key);
    if (!recorded) {
      recorded = { key, value: record.value, sources: new Set() };
      group.recorded.set(key, recorded);
    }
    for (const origin of record.agree) recorded.sources.add(origin);
    for (const claim of record.disagree) {
      const claimKey = JSON.stringify([claim.origin, valueKey(claim.value)]);
      let other = group.other.get(claimKey);
      if (!other) {
        other = {
          origin: claim.origin,
          value: claim.value,
          against: new Set(),
        };
        group.other.set(claimKey, other);
      }
      other.against.add(key);
    }
  }
  return [...groups.values()];
}

function fieldLabel(field: string) {
  if (field === "tag") return "Tags";
  if (field === "alias") return "Title aliases";
  const words = field.replaceAll("_", " ");
  return words.charAt(0).toUpperCase() + words.slice(1);
}

function SourceValue({ value, label }: { value: unknown; label: string }) {
  const id = useId();
  const [expanded, setExpanded] = useState(false);
  if (value === undefined) return <span>Not supplied</span>;
  if (value === "") return <span>Empty text</span>;
  if (Array.isArray(value) && value.length)
    return (
      <ul className="evidence-values">
        {value.map((item, index) => (
          <li key={index}>
            <SourceValue value={item} label={`${label} item ${index + 1}`} />
          </li>
        ))}
      </ul>
    );
  if (typeof value === "string") {
    const long = value.length > 240;
    return (
      <div>
        <p
          id={id}
          className={`catalogue-source-text${long && !expanded ? " is-preview" : ""}`}
        >
          {value}
        </p>
        {long && (
          <button
            className="catalogue-source-toggle"
            aria-label={`${expanded ? "Show less" : "Read full"} ${label}`}
            aria-controls={id}
            aria-expanded={expanded}
            onClick={() => setExpanded((current) => !current)}
          >
            {expanded ? "Show less" : "Read full text"}
          </button>
        )}
      </div>
    );
  }
  return <EvidenceValue value={value} />;
}

export function CatalogueSupport({
  records,
}: {
  records: CatalogueSupportRecord[];
}) {
  const id = useId();
  const groups = groupFields(records);
  const disputed = records.filter(
    (record) => record.disagree.length > 0,
  ).length;
  return (
    <details className="detail-section catalogue-source-support">
      <summary>
        {`Source support · ${groups.length} ${groups.length === 1 ? "field" : "fields"}${disputed ? ` · ${disputed} disputed ${disputed === 1 ? "record" : "records"}` : ""}`}
      </summary>
      {!records.length ? (
        <p>No source support recorded.</p>
      ) : (
        <>
          <p className="context-note">
            {`${records.length} captured ${records.length === 1 ? "record" : "records"}, grouped by field.`}
          </p>
          {groups.map((group, groupIndex) => {
            const recorded = [...group.recorded.values()];
            const other = [...group.other.values()];
            const label = fieldLabel(group.field);
            const groupId = `${id}-field-${groupIndex}`;
            return (
              <section
                key={group.field}
                aria-labelledby={groupId}
                className="catalogue-source-group"
              >
                <h3 id={groupId}>{label}</h3>
                <table className="catalogue-source-table">
                  <caption className="sr-only">Recorded values</caption>
                  <thead>
                    <tr>
                      <th scope="col">Supporting sources</th>
                      <th scope="col">Recorded value</th>
                    </tr>
                  </thead>
                  <tbody>
                    {recorded.map((item, index) => (
                      <tr
                        key={item.key}
                        id={`${groupId}-value-${index}`}
                        tabIndex={-1}
                      >
                        <td>
                          <span
                            className="catalogue-source-cell-label"
                            aria-hidden="true"
                          >
                            Supporting sources
                          </span>
                          {item.sources.size
                            ? [...item.sources].join(", ")
                            : "No supporting source recorded"}
                        </td>
                        <td>
                          <span
                            className="catalogue-source-cell-label"
                            aria-hidden="true"
                          >
                            Recorded value
                          </span>
                          {other.length > 0 && (
                            <span className="catalogue-source-reference">
                              Value {index + 1}
                            </span>
                          )}
                          <SourceValue
                            value={item.value}
                            label={`recorded ${label.toLowerCase()} ${index + 1}`}
                          />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
                {other.length > 0 && (
                  <>
                    <h4>Different source values · {other.length}</h4>
                    <ul
                      className="catalogue-source-alternates"
                      aria-label="Different source values"
                    >
                      {other.map((item, index) => (
                        <li key={index}>
                          <h5>{item.origin || "Source not recorded"}</h5>
                          <SourceValue
                            value={item.value}
                            label={`${label.toLowerCase()} from ${item.origin || "unrecorded source"}`}
                          />
                          <p className="context-note">
                            Compared with{" "}
                            {recorded.map((value, valueIndex) =>
                              item.against.has(value.key) ? (
                                <React.Fragment key={value.key}>
                                  <a
                                    href={`#${groupId}-value-${valueIndex}`}
                                    onClick={(event) => {
                                      if (
                                        event.button !== 0 ||
                                        event.metaKey ||
                                        event.ctrlKey ||
                                        event.shiftKey ||
                                        event.altKey
                                      )
                                        return;
                                      event.preventDefault();
                                      const target = document.getElementById(
                                        `${groupId}-value-${valueIndex}`,
                                      );
                                      target?.focus({ preventScroll: true });
                                      target?.scrollIntoView?.({
                                        block: "nearest",
                                      });
                                    }}
                                  >
                                    value {valueIndex + 1}
                                  </a>{" "}
                                </React.Fragment>
                              ) : null,
                            )}
                          </p>
                        </li>
                      ))}
                    </ul>
                  </>
                )}
              </section>
            );
          })}
          <details className="catalogue-source-raw">
            <summary>Captured source records · {records.length}</summary>
            <EvidenceValue value={records} />
          </details>
        </>
      )}
    </details>
  );
}
