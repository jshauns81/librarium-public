# Pagination

Previous and Next buttons around a tabular page count.

Source: `.pagination` in `style.css` and `reading-room.css`; `Library.tsx`, `App.tsx`.

`filter-label` size, tabular figures, secondary buttons. Below 960px the two buttons sit side by side with the page count centred underneath. Changing page keeps the query and order, and Back returns to the same page and scroll.

The consumer provides the page, total and handlers.
