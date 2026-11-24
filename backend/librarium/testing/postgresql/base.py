"""Owner-only flush for disposable tests; guards remain installed during tests."""

from collections.abc import Iterable

from django.db.backends.postgresql.base import DatabaseWrapper as PostgreSQLWrapper
from django.db.backends.postgresql.operations import DatabaseOperations as PostgreSQLOperations


class DatabaseOperations(PostgreSQLOperations):
    def execute_sql_flush(self, sql_list: Iterable[str]) -> None:
        from django.db import transaction

        # Django's default test database is test_<NAME>; nonstandard names must opt in
        # via TEST.NAME. Never apply this backend to the ordinary configured database.
        expected = self.connection.settings_dict.get("TEST", {}).get("NAME") or (
            "test_" + self.connection.settings_dict["NAME"]
        )
        if self.connection.settings_dict["NAME"] != expected:
            raise RuntimeError("Evidence flush is restricted to the configured test database")
        with transaction.atomic(using=self.connection.alias), self.connection.cursor() as cursor:
            cursor.execute("""
                SELECT n.nspname, c.relname FROM pg_trigger t
                JOIN pg_class c ON c.oid = t.tgrelid
                JOIN pg_namespace n ON n.oid = c.relnamespace
                WHERE t.tgname = 'librarium_evidence_no_truncate'
                  AND n.nspname = current_schema()
                ORDER BY c.relname
            """)
            tables = cursor.fetchall()
            for schema, table in tables:
                cursor.execute(
                    f"ALTER TABLE {self.quote_name(schema)}.{self.quote_name(table)} "
                    "DISABLE TRIGGER librarium_evidence_no_truncate"
                )
            super().execute_sql_flush(sql_list)
            # The maintenance log is not a Django model, so flush never lists it.
            if any(table == "librarium_evidence_maintenance" for _, table in tables):
                cursor.execute("TRUNCATE librarium_evidence_maintenance")
            for schema, table in tables:
                cursor.execute(
                    f"ALTER TABLE {self.quote_name(schema)}.{self.quote_name(table)} "
                    "ENABLE ALWAYS TRIGGER librarium_evidence_no_truncate"
                )


class DatabaseWrapper(PostgreSQLWrapper):
    ops_class = DatabaseOperations
