# BrowseView

A two-button group that switches between Shelves (the default) and List and remembers the choice.

Source: `BrowseView.tsx`; `.browse-view` in `style.css` and `reading-room.css`.

The pressed option uses `aria-pressed="true"`, `accent` text and `selection-fill` (One Fill Rule). In the Reading Room the two buttons share one `line` edge with `radius-control` outer corners. Both views keep the same source series order. If the preference cannot be stored, a `role="status"` notice in `attention` explains that the choice lasts for this visit.

The consumer provides the current view and the change handler.
