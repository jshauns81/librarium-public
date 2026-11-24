"""Read-only admission check using the image's existing runtime grant matrix."""

import json
import os
import sys


class RuntimeGrantRefusal(Exception):
    """A fixed diagnostic from this admission check, never a driver error."""


def verify():
    if any(
        key in os.environ
        for key in ("LIBRARIUM_RUNTIME_DB_USER", "LIBRARIUM_RUNTIME_DB_PASSWORD")
    ):
        raise RuntimeGrantRefusal("shadowed database configuration")
    os.environ.setdefault("DJANGO_SETTINGS_MODULE", "librarium.settings")
    import django

    django.setup()
    from django.db import connection, transaction
    from librarium.management.commands.provision_runtime_role import (
        EVIDENCE,
        MUTABLE,
        READ_ONLY,
    )

    expected = "librarium_runtime"
    with transaction.atomic(), connection.cursor() as cursor:
        cursor.execute("SET TRANSACTION READ ONLY")
        cursor.execute("SET LOCAL statement_timeout = '5000ms'")
        cursor.execute("SELECT current_user")
        if cursor.fetchone()[0] != expected:
            raise RuntimeGrantRefusal("unexpected effective login")
        cursor.execute("""
            SELECT oid, rolcanlogin, rolsuper, rolcreatedb, rolcreaterole,
                   rolreplication, rolbypassrls FROM pg_roles WHERE rolname = current_user
        """)
        role = cursor.fetchone()
        if not role or not role[1] or any(role[2:]):
            raise RuntimeGrantRefusal("elevated runtime login")
        cursor.execute(
            """
            SELECT EXISTS (SELECT 1 FROM pg_auth_members WHERE member = %s)
                OR EXISTS (SELECT 1 FROM pg_shdepend WHERE refclassid = 'pg_authid'::regclass
                           AND refobjid = %s AND deptype = 'o')
        """,
            [role[0], role[0]],
        )
        if cursor.fetchone()[0]:
            raise RuntimeGrantRefusal("runtime owns objects or inherits roles")
        cursor.execute("""
            SELECT has_database_privilege(current_user, current_database(), 'CREATE'),
                   has_database_privilege(current_user, current_database(), 'TEMPORARY'),
                   has_parameter_privilege(current_user, 'session_replication_role', 'SET'),
                   EXISTS (SELECT 1 FROM pg_namespace
                           WHERE has_schema_privilege(current_user, oid, 'CREATE'))
        """)
        if any(cursor.fetchone()):
            raise RuntimeGrantRefusal("runtime has owner capabilities")
        cursor.execute("""
            SELECT relname FROM pg_class c JOIN pg_namespace n ON n.oid=c.relnamespace
            WHERE n.nspname='public' AND c.relkind IN ('r','p','v','m','f')
        """)
        if {row[0] for row in cursor.fetchall()} != {*EVIDENCE, *MUTABLE, *READ_ONLY}:
            raise RuntimeGrantRefusal("unclassified runtime tables")
        for table in (*EVIDENCE, *MUTABLE, *READ_ONLY):
            for privilege in (
                "SELECT",
                "INSERT",
                "UPDATE",
                "DELETE",
                "TRUNCATE",
                "TRIGGER",
                "REFERENCES",
                "MAINTAIN",
            ):
                allowed = (
                    privilege == "SELECT"
                    or privilege == "INSERT"
                    and table in (*EVIDENCE, *MUTABLE)
                    or privilege in {"UPDATE", "DELETE"}
                    and table in MUTABLE
                )
                cursor.execute(
                    "SELECT has_table_privilege(current_user, %s, %s)",
                    [table, privilege],
                )
                if cursor.fetchone()[0] != allowed:
                    raise RuntimeGrantRefusal("runtime grant matrix mismatch")
                if not allowed and privilege in {"INSERT", "UPDATE", "REFERENCES"}:
                    cursor.execute(
                        "SELECT has_any_column_privilege(current_user, %s, %s)",
                        [table, privilege],
                    )
                    if cursor.fetchone()[0]:
                        raise RuntimeGrantRefusal("unexpected runtime column privilege")
    return {"current_user": expected, "runtime_grants_verified": True}


if __name__ == "__main__":
    try:
        result = verify()
    except RuntimeGrantRefusal as error:
        print(f"Runtime database verification refused: {error}", file=sys.stderr)
        raise SystemExit(1) from None
    except Exception as error:  # noqa: BLE001 - suppress connection details and secrets.
        print(
            f"Runtime database verification refused ({type(error).__name__})",
            file=sys.stderr,
        )
        raise SystemExit(1) from None
    print(json.dumps(result, sort_keys=True))
