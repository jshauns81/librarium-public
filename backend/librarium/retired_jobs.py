"""Job kinds Librarium no longer runs; their stored rows remain readable history.

Librarium reads and checks books and reports problems; it no longer produces
corrected copies or delivers them. Rows of these kinds stay in the database as
plain records. No worker claims or advances them, they link to no report, and an
operator can still cancel one that was left queued or running.
"""

GENERATION_KINDS = frozenset({"epub_correction", "output_validation"})
DELIVERY_KINDS = frozenset({"delivery_prepare", "epub_delivery", "delivery_reconcile", "epub_undo"})
RETIRED_KINDS = GENERATION_KINDS | DELIVERY_KINDS

# History and list filters accept this word for all six kinds at once.
FILTER = "retired"
OPEN_STATES = frozenset({"queued", "running"})

CANCELLED_MESSAGE = "Cancelled; this kind of work is retired and was not continued"
UNFINISHED_MESSAGE = "Retired work that was never finished; it will not run"
