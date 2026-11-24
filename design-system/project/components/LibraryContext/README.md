# LibraryContext

The quiet summary of how complete the library check is, with a Details popover for version, snapshot and reload.

Source: `.library-context`, `.check-dot`, `.library-check-details` in `reading-room.css`; `Library.tsx`.

A `meta` `muted` summary: the 0.55rem `copper` check dot, the coverage label, the date (hidden below 960px) and an underlined `accent` `Details`. The popover is `surface`, `soft-line` border, `radius-control`, `shadow-popover`, up to 28rem wide. It states what the coverage supports (`Ownership is supported at the recorded check time.` or `Unlisted titles may still be in Calibre.`) and offers `Reload library`, which reads `Reading library…` while fetching.

The consumer provides coverage, check time, catalogue version, snapshot and the reload handler.
