# ThemePicker

A labelled select that applies Dark, Light or System immediately and remembers it. With a connected library the rooms are chosen in Settings instead.

Source: `ThemePicker.tsx`, `theme.ts`, `themes.ts`, `theme-assets.ts`.

`small` `muted` label and a 9rem select (8rem, 7.2rem as the masthead narrows; the label is visually hidden below 620px but still names the control). The choice is stored under `librarium.theme` and synchronized across tabs; if storage is unavailable switching still works for the visit and a `role="status"` line in `attention` says so. System follows the device through Catppuccin Latte and Mocha. A same-origin pre-paint script applies the theme before first paint, so there is no flash.

The consumer provides nothing; the component owns the registry.
