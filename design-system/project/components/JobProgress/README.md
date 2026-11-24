# JobProgress

The live state of a durable inspection or catalogue review: a word, the exact step, a bar, and the findings once they exist.

Source: `JobProgress.tsx`, `CatalogueReview.tsx`; `.job-progress`, `.state`, `progress`, `.findings` in `style.css`.

- State word in bold: `accent` for queued, running and complete, `attention` for failed, `muted` for cancelled. Labels are in **Status labels**; what they may claim is in **UX standards**.
- Queued and running show `N / 4 steps` in tabular `muted` and a square `progress-height` bar (`accent` on `progress-track`, advancing over 180ms).
- Findings read `Passed`, `Attention`, `Partial` or `Not checked`, then ` · ` and the finding name; `Finding details` and the review record (with **Provenance**) sit in disclosures.
- Announce terminal states through a `role="status"` region. Navigation and Cancel stay available while a job runs. Show only server-confirmed results.
- Label synthetic fixture reviews `Synthetic fixture review` and keep them apart from real reviews.

The consumer provides the job (state, checkpoint, result, identifiers) and whether to announce it.
