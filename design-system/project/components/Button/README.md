# Button

A named control that acts on its task; secondary by default, `primary` only for the one action that owns the task.

Source: base `button` rules, `.primary`, `.text-button` in `frontend/src/style.css`.

- **Secondary** (plain `button` or `.secondary`): transparent, `ink` label, `line` edge, `radius-control`, padding 0.45rem 0.8rem, at least `control-min` tall (`target-coarse` on coarse pointers). Hover and press fill with `pressed-fill` over 160ms.
- **Primary** (`.primary`): `accent` fill and edge, `on-accent` label at weight 600, `accent-hover` on hover. Use for starting a review or the first-run action, never for navigation.
- **Disabled**: opacity `disabled` (0.6), default cursor. Prefer a progress label (`Reading library…`) over silently disabling.
- **Text button** (`.text-button`): no edge, Literata 1.05rem, underline on hover. For a title that opens its work in history rows.
- Focus is the `focus-ring` in `accent`, offset 4px, on every surface.

The consumer provides the label (sentence case, a verb) and the handler. Keep refresh, retry, clear, cancel, Back and pagination secondary.
