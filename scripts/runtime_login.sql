\set ON_ERROR_STOP on
-- Bootstrap runs as the pinned database image's owner. Never echo secret SQL.
SET log_statement = 'none';
SET log_min_error_statement = 'panic';
SET log_min_duration_statement = -1;
SET log_min_duration_sample = -1;
SET log_duration = off;
SET log_transaction_sample_rate = 0;
\getenv runtime_password RUNTIME_PASSWORD
SELECT length(:'runtime_password') BETWEEN 32 AND 256 AS password_valid \gset
\if :password_valid
\else
  SELECT 1 / 0;
\endif
BEGIN;
SELECT pg_advisory_xact_lock(7304162906431);
SELECT NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'librarium_runtime') AS role_absent \gset
\if :role_absent
  CREATE ROLE librarium_runtime LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE
    NOREPLICATION NOBYPASSRLS PASSWORD :'runtime_password';
\endif
COMMIT;
