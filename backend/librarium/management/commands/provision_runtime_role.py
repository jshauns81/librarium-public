"""Grant a fresh, pre-created login only the runtime DML it needs."""

from typing import Any

from django.core.management.base import BaseCommand, CommandError, CommandParser
from django.db import connection, transaction

EVIDENCE = (
    "librarium_deliveryintent",
    "librarium_deliveryapproval",
    "librarium_deliverytargetbinding",
    "librarium_deliveryevent",
    "librarium_deliveryreceipt",
    "librarium_undointent",
    "librarium_coverreviewaction",
    "librarium_preparedcover",
)
MUTABLE = (
    "librarium_sourcebrowserpage",
    "librarium_coversearch",
    "librarium_covercensus",
    "librarium_coverreviewentry",
    "librarium_work",
    "librarium_job",
    "librarium_libraryreconciliation",
    "librarium_correctedepub",
    "librarium_deliverystate",
    # The worker replaces the library read model whole on each Calibre change.
    "librarium_libraryreadmodel",
    "librarium_cataloguestatus",
    "librarium_calibrebook",
    "librarium_calibreauthor",
    "librarium_calibrebookauthor",
    "librarium_calibreseries",
    "librarium_calibrepublisher",
    "librarium_calibrelanguage",
    "librarium_calibrebooklanguage",
    "librarium_calibreidentifier",
    "librarium_calibreformat",
)
READ_ONLY = ("django_content_type", "django_migrations", "librarium_evidence_maintenance")


class Command(BaseCommand):
    help = "Provision an existing dedicated runtime login in the current owned database"

    def add_arguments(self, parser: CommandParser) -> None:
        parser.add_argument("role")

    def handle(self, *args: Any, **options: Any) -> None:
        role = options["role"]

        def quote(value: str) -> str:
            return '"' + value.replace('"', '""') + '"'

        with transaction.atomic(), connection.cursor() as cursor:
            cursor.execute(
                """
                SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                       rolreplication, rolbypassrls FROM pg_roles WHERE rolname = %s
            """,
                [role],
            )
            attributes = cursor.fetchone()
            if not attributes or not attributes[1] or any(attributes[2:]):
                raise CommandError("Use a dedicated LOGIN without elevated role attributes")
            oid = attributes[0]
            cursor.execute(
                """
                SELECT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = %s)
                    OR EXISTS (SELECT 1 FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass
                               AND refobjid = %s AND deptype = 'o')
            """,
                [oid, oid],
            )
            if cursor.fetchone()[0]:
                raise CommandError("Runtime must have no memberships or owned objects")
            cursor.execute("""
                SELECT d.datname, n.nspname,
                       d.datdba = current_user::regrole,
                       pg_has_role(current_user, n.nspowner, 'USAGE')
                FROM pg_database d, pg_namespace n
                WHERE d.datname = current_database() AND n.nspname = current_schema()
            """)
            database, schema, owns_database, owns_schema = cursor.fetchone()
            if schema != "public" or not owns_database or not owns_schema:
                raise CommandError("Run as the database and public-schema owner after migrations")
            cursor.execute(
                """
                SELECT c.relname, c.relowner = current_user::regrole
                FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE n.nspname = %s AND c.relkind IN ('r', 'p', 'v', 'm', 'f')
            """,
                [schema],
            )
            tables = cursor.fetchall()
            if {name for name, _ in tables} != {*EVIDENCE, *MUTABLE, *READ_ONLY} or not all(
                owned for _, owned in tables
            ):
                raise CommandError(
                    "Unclassified or non-owned tables; review the runtime grant matrix"
                )
            cursor.execute(
                """
                SELECT has_parameter_privilege(%s, 'session_replication_role', 'SET')
            """,
                [role],
            )
            if cursor.fetchone()[0]:
                raise CommandError("Runtime must not have SET on session_replication_role")
            target = quote(role)
            # PUBLIC privileges are inherited by every login, even NOINHERIT roles.
            cursor.execute(f"REVOKE CREATE, TEMPORARY ON DATABASE {quote(database)} FROM PUBLIC")
            cursor.execute(f"REVOKE ALL ON DATABASE {quote(database)} FROM {target}")
            cursor.execute(f"GRANT CONNECT ON DATABASE {quote(database)} TO {target}")
            cursor.execute("REVOKE CREATE ON SCHEMA public FROM PUBLIC")
            cursor.execute(f"REVOKE ALL ON SCHEMA public FROM {target}")
            cursor.execute(f"GRANT USAGE ON SCHEMA public TO {target}")
            for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                cursor.execute(f"REVOKE ALL ON ALL {kind} IN SCHEMA public FROM PUBLIC, {target}")
            cursor.execute(
                "SELECT EXISTS (SELECT 1 FROM pg_namespace "
                "WHERE nspname <> 'public' AND has_schema_privilege(%s, oid, 'CREATE'))",
                [role],
            )
            if cursor.fetchone()[0]:
                raise CommandError("Runtime must not have CREATE in other schemas")
            cursor.execute(f"ALTER DEFAULT PRIVILEGES REVOKE ALL ON SCHEMAS FROM PUBLIC, {target}")
            for scope in ("", " IN SCHEMA public"):
                for kind in ("TABLES", "SEQUENCES", "FUNCTIONS"):
                    cursor.execute(
                        f"ALTER DEFAULT PRIVILEGES{scope} REVOKE ALL ON {kind} FROM PUBLIC, {target}"
                    )
            for table in (*EVIDENCE, *MUTABLE, *READ_ONLY):
                privileges = "SELECT"
                if table in EVIDENCE:
                    privileges += ", INSERT"
                if table in MUTABLE:
                    privileges += ", INSERT, UPDATE, DELETE"
                cursor.execute(f"GRANT {privileges} ON TABLE {quote(table)} TO {target}")
        self.stdout.write("Runtime grants applied; re-run after reviewing future schema changes")
