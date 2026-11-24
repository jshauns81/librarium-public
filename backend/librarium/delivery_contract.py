"""Policy identity shared by the isolated library-write path.

Corrected-copy generation and its delivery orchestration are retired; the writer
core keeps only the policy name it binds into authorizations and receipts.
"""

POLICY = "librarium.epub-delivery.v1"
