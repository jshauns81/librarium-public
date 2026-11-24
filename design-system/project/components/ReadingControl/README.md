# ReadingControl

A compact labelled select for ordering and filtering the shelves, with the label inside the control's edge.

Source: `.reading-control` in `reading-room.css`; rendered by `Library.tsx`.

One `line` edge with `radius-control` wraps a `muted` 0.85rem label and a borderless 0.95rem select, at least `control-min` (44px below 960px and on coarse pointers). Keep options short: `Series`, `Title`, `Author`; `All books`, `Direct matches`, `Inside collections`. Pair the Order control with an order description in words (`Shelved by series, in recorded order`).

The consumer provides the label, the options and the change handler.
