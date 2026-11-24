# Public compatibility baseline

Public container acceptance exercises the candidate image and rehearses a populated upgrade from a pinned historical runtime fixture. Synthetic book data and the test database are created on the runner. The private release pipeline retains its separate check against the released image and configuration digests.

The trusted workflow policy permits a required job to move from the existing runner selector to literal `ubuntu-24.04`. This allows a follow-up change to pin all workflow jobs through ordinary protected review.
