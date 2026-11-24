# ErrorNotice

The visual treatment for a failure notice and its inline recovery controls.

Source: `.error` in `style.css`; used across `App.tsx`, `Library.tsx`, `Catalogue.tsx`.

`attention` text, an `attention-line` border, `radius-control`, padding `space-stack`, with inline recovery buttons. Use `role="alert"` for new failures. What the notice must say and keep visible is owned by **UX standards** (Truth, status and actions).

The consumer provides the message (what happened, effect) and the recovery actions.
