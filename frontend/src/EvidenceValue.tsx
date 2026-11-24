import React from "react";

export function EvidenceValue({ value }: { value: unknown }) {
  if (value == null) return <span>Not recorded</span>;
  if (Array.isArray(value)) {
    return value.length ? (
      <ul className="evidence-values">
        {value.map((item, i) => (
          <li key={i}>
            <EvidenceValue value={item} />
          </li>
        ))}
      </ul>
    ) : (
      <span>Empty list</span>
    );
  }
  if (typeof value === "object") {
    const entries = Object.entries(value);
    return entries.length ? (
      <dl className="evidence-fields">
        {entries.map(([name, item]) => (
          <React.Fragment key={name}>
            <dt>{name}</dt>
            <dd>
              <EvidenceValue value={item} />
            </dd>
          </React.Fragment>
        ))}
      </dl>
    ) : (
      <span>Empty object</span>
    );
  }
  return <span>{String(value)}</span>;
}
