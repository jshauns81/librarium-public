// Librarium reads and checks books; it no longer makes review copies or delivers
// them. Old jobs of these kinds remain in the record as plain past entries.
export const RETIRED_KINDS = [
  "epub_correction",
  "output_validation",
  "delivery_prepare",
  "epub_delivery",
  "delivery_reconcile",
  "epub_undo",
] as const;

export type RetiredKind = (typeof RETIRED_KINDS)[number];

export const isRetiredKind = (kind: string | undefined | null): boolean =>
  !!kind && (RETIRED_KINDS as readonly string[]).includes(kind);

const retiredLabels: Record<RetiredKind, string> = {
  epub_correction: "Review copy",
  output_validation: "Review copy check",
  delivery_prepare: "Delivery preparation",
  epub_delivery: "Delivery",
  delivery_reconcile: "Delivery outcome check",
  epub_undo: "Delivery undo",
};

export function retiredKindLabel(kind: string | undefined | null): string {
  return isRetiredKind(kind) ? retiredLabels[kind as RetiredKind] : "Record";
}
