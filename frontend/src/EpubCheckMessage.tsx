import React from "react";

export function EpubCheckMessage({
  id,
  message,
  className,
}: {
  id: string;
  message: string;
  className?: string;
}) {
  const explanation: Record<string, string> = {
    OPF_053: "A package date does not use the recommended date format.",
    OPF_054: "A package date is invalid.",
  };
  const code = id.replace("-", "_");
  const summary = Object.hasOwn(explanation, code)
    ? explanation[code]
    : undefined;
  return summary ? (
    <>
      <p className={className}>{summary}</p>
      <details>
        <summary>Exact EPUBCheck diagnostic</summary>
        <p className={className}>{message}</p>
      </details>
    </>
  ) : (
    <p className={className}>{message}</p>
  );
}
