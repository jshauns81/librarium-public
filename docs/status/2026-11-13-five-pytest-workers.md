# Five pytest workers

Pytest defaults to five xdist workers. Native writer proofs use serial execution because they share fixed ports and process state.
