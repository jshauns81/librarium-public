# Delivery evidence protection, 2026-10-31

[L062](../decisions.md#l062-postgresql-guards-and-a-separate-runtime-login) adds ALWAYS
row and statement-level TRUNCATE guards, an append-only maintenance record and
owner-run runtime-login provisioning. Six immutable evidence tables and the
reservation projection refuse owner TRUNCATE; runtime lacks DDL and destructive
evidence privileges. Test-only atomic flush preserves Django transactional cleanup
while tests exercise the installed production guards. Deployment/credential
activation and real-library use remain separately approved.
