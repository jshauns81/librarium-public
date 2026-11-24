# BLC schema contract

`blc-schema.sql` is byte-for-byte committed source from
`jshauns81/bl-catalog`, commit `a8f274487f09399a6fe90f4210bb50fc0c3a0701`,
path `src/bl_catalog/db/schema.sql`. SHA-256:
`dff500b1f4ae5537fe6a613ee32cd78e7f8a7db83e5280dbcbdc8de822ad27d3`.
The contract test checks this hash. Change it only with an explicit upstream
contract review. Tests execute this schema in temporary fixture databases;
they never import or run BLC's harvest/resolver/writer engines.

Inserted works, authors, identifiers and support rows are fictional. They prove
reader compatibility with the schema, not resolver or live-data parity.
