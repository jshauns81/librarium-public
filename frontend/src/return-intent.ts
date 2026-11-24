export type ReturnIntent = {
  isCurrent: () => boolean;
  dispose: () => void;
};

export function trackReturnIntent(
  onCancel: () => void,
  { includeCurrentFocus = false }: { includeCurrentFocus?: boolean } = {},
): ReturnIntent {
  let current = includeCurrentFocus || document.activeElement === document.body;
  const events = [
    "focusin",
    "pointerdown",
    "keydown",
    "wheel",
    "touchmove",
  ] as const;
  const dispose = () => {
    current = false;
    for (const event of events)
      document.removeEventListener(event, cancel, true);
  };
  const cancel = () => {
    if (!current) return;
    dispose();
    onCancel();
  };
  if (current)
    for (const event of events)
      document.addEventListener(event, cancel, {
        capture: true,
        passive: true,
      });
  return { isCurrent: () => current, dispose };
}
