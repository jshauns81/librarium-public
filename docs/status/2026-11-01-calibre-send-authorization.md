# Calibre send authorization, 2026-11-01

The writer rechecks review expiry, writer identity and protected supervision
after artifact and initial Calibre reads, then again after the final observation
immediately before replacement. Delivery and Undo that expire during preflight
are durably sealed as not applied. Their operation key and session stay consumed;
recovery never resends them, and a proven no-send refusal does not pause other
requests. Twelve controlled-clock regressions cover review/session expiry during
artifact reads and both observations, including restart recovery. Real-library
activation remains unapproved.
