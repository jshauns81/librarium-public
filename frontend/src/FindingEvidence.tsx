import React, { useId, useState } from "react";
import { EvidenceValue } from "./EvidenceValue";
import "./finding-evidence.css";

type SourceValue = {
  value: unknown;
  value_truncated: boolean;
  [key: string]: unknown;
};
type SourceItem = SourceValue & {
  field: string;
  agree: string[];
  agree_count: number;
  disagree: (SourceValue & { origin: string })[];
  disagree_count: number;
};
const record = (value: unknown): value is Record<string, unknown> =>
  !!value && typeof value === "object" && !Array.isArray(value);
const sourceValue = (value: unknown): boolean =>
  record(value) &&
  Object.hasOwn(value, "value") &&
  typeof value.value_truncated === "boolean";
function sourceItem(value: unknown): value is SourceItem {
  return (
    record(value) &&
    sourceValue(value) &&
    typeof value.field === "string" &&
    Array.isArray(value.agree) &&
    value.agree.every((item) => typeof item === "string") &&
    Number.isSafeInteger(value.agree_count) &&
    (value.agree_count as number) >= value.agree.length &&
    Array.isArray(value.disagree) &&
    value.disagree.every(
      (item) =>
        sourceValue(item) && record(item) && typeof item.origin === "string",
    ) &&
    Number.isSafeInteger(value.disagree_count) &&
    (value.disagree_count as number) >= value.disagree.length
  );
}
function fieldLabel(field: string) {
  const label = field.replaceAll("_", " ");
  return label.charAt(0).toUpperCase() + label.slice(1);
}
function ComparisonValue({ value, label }: { value: unknown; label: string }) {
  const id = useId();
  const [expanded, setExpanded] = useState(false);
  if (typeof value !== "string" || value.length <= 240)
    return <EvidenceValue value={value} />;
  return (
    <div>
      <p
        id={id}
        className={`source-value-text${expanded ? "" : " is-preview"}`}
      >
        {value}
      </p>
      <button
        className="source-value-toggle"
        aria-label={`${expanded ? "Show less" : "Read captured"} ${label}`}
        aria-controls={id}
        aria-expanded={expanded}
        onClick={() => setExpanded((current) => !current)}
      >
        {expanded ? "Show less" : "Read captured text"}
      </button>
    </div>
  );
}

function valueKey(value: unknown): string {
  if (value === null) return "null";
  if (Array.isArray(value))
    return `list:${JSON.stringify(value.map(valueKey))}`;
  if (record(value))
    return `object:${JSON.stringify(
      Object.keys(value)
        .sort()
        .map((key) => [key, valueKey(value[key])]),
    )}`;
  return `${typeof value}:${Object.is(value, -0) ? "-0" : String(value)}`;
}

function valueType(value: unknown) {
  if (value === null) return "Null";
  if (Array.isArray(value)) return "List";
  const types: Record<string, string> = {
    string: "Text",
    boolean: "Boolean",
    number: "Number",
    object: "Object",
  };
  return types[typeof value] ?? "Not recorded";
}

// A source's values arrive as a list, or as that list's JSON text. Text cut at
// the capture limit no longer parses and stays exactly as recorded.
function recordedValues({ value, value_truncated }: SourceValue) {
  let values = value;
  if (typeof value === "string" && value.startsWith("["))
    try {
      values = JSON.parse(value);
    } catch {
      values = value;
    }
  if (!Array.isArray(values) || !values.length)
    return [{ value, excerpt: value_truncated }];
  return values.map((part, index) => ({
    value: part,
    excerpt: value_truncated && index === values.length - 1,
  }));
}

const itemFields = [
  "field",
  "value",
  "value_truncated",
  "agree",
  "agree_count",
  "disagree",
  "disagree_count",
  "origin",
];
function qualifiers(item: SourceValue) {
  return Object.entries(item)
    .filter(([key]) => !itemFields.includes(key))
    .map(
      ([key, value]) =>
        `${key}: ${typeof value === "string" ? value : JSON.stringify(value)}`,
    );
}

type Row = {
  key: string;
  value: unknown;
  excerpt: boolean;
  sources: Set<string>;
  notes: Set<string>;
};

function fieldRows(items: SourceItem[]) {
  const rows = new Map<string, Row>();
  function add(item: SourceValue, sources: string[]) {
    for (const { value, excerpt } of recordedValues(item)) {
      // Equal excerpts do not show equal originals, so each source keeps its own.
      const key = excerpt
        ? `excerpt:${valueKey(value)}:${sources.join("\n")}`
        : valueKey(value);
      let row = rows.get(key);
      if (!row) {
        row = { key, value, excerpt, sources: new Set(), notes: new Set() };
        rows.set(key, row);
      }
      sources.forEach((source) => row.sources.add(source));
      qualifiers(item).forEach((note) => row.notes.add(note));
    }
  }
  for (const item of items) {
    add(item, item.agree);
    for (const other of item.disagree) add(other, [other.origin]);
  }
  return [...rows.values()].sort((a, b) => b.sources.size - a.sources.size);
}

function SourceTable({ field, items }: { field: string; items: SourceItem[] }) {
  const rows = fieldRows(items);
  const label = fieldLabel(field);
  const mixedTypes = new Set(rows.map((row) => valueType(row.value))).size > 1;
  const unlisted = items.some(
    (item) =>
      item.agree_count > item.agree.length ||
      item.disagree_count > item.disagree.length,
  );
  return (
    <section>
      <table>
        <caption>{label}</caption>
        <thead>
          <tr>
            <th scope="col">Value</th>
            <th scope="col">Supported by</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((row) => (
            <tr key={row.key}>
              <th scope="row">
                <div className="source-value">
                  <ComparisonValue value={row.value} label={`${label} value`} />
                </div>
                {mixedTypes && (
                  <p className="source-note">{valueType(row.value)}</p>
                )}
                {row.excerpt && (
                  <p className="source-note">
                    Excerpt; full value not captured
                  </p>
                )}
                {[...row.notes].map((note) => (
                  <p className="source-note" key={note}>
                    {note}
                  </p>
                ))}
              </th>
              <td>
                {row.sources.size ? (
                  <ul className="source-names">
                    {[...row.sources].map((source) => (
                      <li key={source}>{source}</li>
                    ))}
                  </ul>
                ) : (
                  <span className="source-note">No source listed</span>
                )}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
      {unlisted && (
        <p className="source-note">
          Some source records for this field are counted but not listed.
        </p>
      )}
    </section>
  );
}

const scalar = (value: unknown) =>
  value === null || ["string", "number", "boolean"].includes(typeof value);

function FlatItems({ name, items }: { name: string; items: unknown[] }) {
  const rows = items as Record<string, unknown>[];
  const columns = [...new Set(rows.flatMap((row) => Object.keys(row)))];
  return (
    <div className="source-comparisons">
      <table>
        <caption className="sr-only">{name} items</caption>
        <thead>
          <tr>
            {columns.map((column) => (
              <th scope="col" key={column}>
                {fieldLabel(column)}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {rows.map((row, index) => (
            <tr key={index}>
              {columns.map((column) => (
                <td key={column}>
                  <EvidenceValue value={row[column]} />
                </td>
              ))}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

export function FindingEvidence({
  name,
  items,
}: {
  name: string;
  items: unknown[];
}) {
  if (name === "Source agreement" && items.length && items.every(sourceItem)) {
    const fields = new Map<string, SourceItem[]>();
    for (const item of items)
      fields.set(item.field, [...(fields.get(item.field) ?? []), item]);
    return (
      <div className="source-comparisons">
        <p className="source-note">
          A supporting source may record a compatible form, such as a year for a
          full date.
        </p>
        {[...fields].map(([field, records]) => (
          <SourceTable key={field} field={field} items={records} />
        ))}
        <details className="source-raw">
          <summary>Raw record</summary>
          <pre
            className="source-raw-text"
            role="region"
            aria-label="Raw source agreement records"
            tabIndex={0}
          >
            {items.map((item) => JSON.stringify(item)).join("\n")}
          </pre>
        </details>
      </div>
    );
  }
  if (
    items.length &&
    items.every(
      (item) =>
        record(item) &&
        Object.keys(item).length &&
        Object.values(item).every(scalar),
    )
  )
    return <FlatItems name={name} items={items} />;
  return <EvidenceValue value={items} />;
}
