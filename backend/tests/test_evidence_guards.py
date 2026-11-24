"""Real PostgreSQL owner guards, runtime privileges and atomic Django cleanup."""

import os
import secrets
import uuid

import psycopg
import pytest
from django.core.management import call_command
from django.core.management.color import no_style
from django.db import DatabaseError, connection, transaction
from librarium.models import (
    CoverCensus,
    CoverReviewAction,
    CoverReviewEntry,
    DeliveryEvent,
    DeliveryReceipt,
    PreparedCover,
    UndoIntent,
)
from psycopg import sql
from retired_history import make_delivery, make_job, make_output, record

EVIDENCE = (
    "deliveryintent",
    "deliveryapproval",
    "deliverytargetbinding",
    "deliveryevent",
    "deliveryreceipt",
    "undointent",
    "coverreviewaction",
    "preparedcover",
)
MUTABLE = ("deliverystate", "covercensus", "coverreviewentry")
TABLES = tuple("librarium_" + name for name in (*EVIDENCE, *MUTABLE))


@pytest.fixture
def evidence(db):
    for _ in range(2):
        census = CoverCensus.objects.create(
            request_key=uuid.uuid4(),
            library_uuid="fixture-library",
            inventory_token="fixture",
            detector="fixture",
            state="complete",
        )
        entry = CoverReviewEntry.objects.create(
            library_uuid=census.library_uuid,
            book_uuid=str(uuid.uuid4()),
            calibre_id=1,
        )
        CoverReviewAction.objects.create(
            request_key=uuid.uuid4(),
            entry=entry,
            expected_revision=1,
            skipped=True,
            actor="reviewer",
            result={"state": "skipped"},
        )
        PreparedCover.objects.create(
            request_key=uuid.uuid4(),
            entry=entry,
            actor="reviewer",
            request={},
            binding={},
            candidate={},
        )
        output, jobs = make_output()
        job, intent, _ = make_delivery(output, jobs, reserved=False)
        record(DeliveryEvent, {"code": "observed"}, intent=intent, job=job)
        receipt = record(DeliveryReceipt, {}, intent=intent, job=job, operation_id=uuid.uuid4())
        record(
            UndoIntent,
            {},
            delivery=intent,
            receipt=receipt,
            job=make_job("epub_undo", output.pk),
        )


@pytest.mark.django_db
@pytest.mark.parametrize("table", TABLES)
def test_owner_cannot_truncate_even_empty_tables(table):
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute(f'TRUNCATE "{table}" CASCADE')


@pytest.mark.parametrize("mode", ["origin", "replica"])
@pytest.mark.parametrize("action", ["UPDATE", "DELETE"])
@pytest.mark.parametrize("table", EVIDENCE)
def test_bulk_rewrites_and_deletes_are_refused(evidence, table, action, mode):
    with connection.cursor() as cursor:
        cursor.execute(f'SELECT count(*) FROM "librarium_{table}"')
        assert cursor.fetchone()[0] == 2
    # The admin connection can SET replica; the non-superuser owner cannot.
    params = connection.get_connection_params()
    params.pop("cursor_factory", None)
    params.pop("context", None)
    params.pop("prepare_threshold", None)
    params["user"] = os.environ.get("LIBRARIUM_TEST_ADMIN_USER", params.get("user"))
    with psycopg.connect(**params, autocommit=True) as admin:
        # Uncommitted Django fixtures are visible only on the Django connection.
        # Grant just this parameter to the disposable test owner for this check.
        owner = connection.settings_dict["USER"]
        admin.execute(
            sql.SQL("GRANT SET ON PARAMETER session_replication_role TO {}").format(
                sql.Identifier(owner)
            )
        )
        try:
            with transaction.atomic(), connection.cursor() as cursor:
                cursor.execute("SET LOCAL session_replication_role = " + mode)
                with (
                    pytest.raises(DatabaseError, match="append-only"),
                    transaction.atomic(),
                    connection.cursor() as cursor,
                ):
                    field = (
                        "result"
                        if table == "coverreviewaction"
                        else "binding"
                        if table == "preparedcover"
                        else "payload"
                    )
                    statement = (
                        f'UPDATE "librarium_{table}" SET {field} = {field}'
                        if action == "UPDATE"
                        else f'DELETE FROM "librarium_{table}"'
                    )
                    cursor.execute(statement)
        finally:
            admin.execute(
                sql.SQL("REVOKE SET ON PARAMETER session_replication_role FROM {}").format(
                    sql.Identifier(owner)
                )
            )


@pytest.mark.django_db
def test_all_guards_are_always_enabled():
    with connection.cursor() as cursor:
        cursor.execute("""
            SELECT c.relname, t.tgname, t.tgenabled FROM pg_trigger t
            JOIN pg_class c ON c.oid = t.tgrelid
            WHERE t.tgname = 'librarium_evidence_no_truncate' OR t.tgname LIKE 'immutable_%%'
        """)
        guards = cursor.fetchall()
    assert {t for t, n, e in guards if n == "librarium_evidence_no_truncate"} >= set(TABLES)
    assert all(enabled == "A" for _, _, enabled in guards)


@pytest.fixture
def runtime_role(transactional_db, request):
    name = "librarium_guard_runtime_" + uuid.uuid4().hex[:12] + getattr(request, "param", "")
    params = connection.get_connection_params()
    for key in ("cursor_factory", "context", "prepare_threshold"):
        params.pop(key, None)
    params["user"] = os.environ.get("LIBRARIUM_TEST_ADMIN_USER", params.get("user"))
    with psycopg.connect(**params, autocommit=True) as admin:
        # A generated password lets password-authenticated servers admit the login too.
        password = secrets.token_urlsafe(24)
        admin.execute(
            sql.SQL("CREATE ROLE {} LOGIN PASSWORD {}").format(
                sql.Identifier(name), sql.Literal(password)
            )
        )
        try:
            yield name, admin, password
        finally:
            admin.execute("DROP TABLE IF EXISTS librarium_guard_future")
            admin.execute(sql.SQL("DROP OWNED BY {}").format(sql.Identifier(name)))
            admin.execute(sql.SQL("DROP ROLE {}").format(sql.Identifier(name)))


@pytest.mark.parametrize("runtime_role", ["", '"quoted'], indirect=True)
def test_runtime_privilege_matrix(runtime_role, evidence):
    name, _admin, password = runtime_role
    with connection.cursor() as cursor:
        # Clear inherited and default grants as well as direct current-object grants.
        cursor.execute("ALTER DEFAULT PRIVILEGES GRANT ALL ON TABLES TO PUBLIC")
        cursor.execute("ALTER DEFAULT PRIVILEGES IN SCHEMA public GRANT ALL ON TABLES TO PUBLIC")
    call_command("provision_runtime_role", name, verbosity=0)
    call_command("provision_runtime_role", name, verbosity=0)
    with connection.cursor() as cursor:
        cursor.execute("CREATE TABLE librarium_guard_future(id integer)")
    params = connection.get_connection_params()
    for key in ("cursor_factory", "context", "prepare_threshold"):
        params.pop(key, None)
    params["user"] = name
    params["password"] = password
    with psycopg.connect(**params, autocommit=True) as runtime:
        assert runtime.execute(
            "SELECT has_table_privilege(current_user, 'librarium_cataloguestatus', 'SELECT, INSERT, UPDATE, DELETE')"
        ).fetchone()[0]
        for table in TABLES:
            row = runtime.execute(
                "SELECT has_table_privilege(current_user, %s, 'SELECT'), "
                "has_table_privilege(current_user, %s, 'INSERT'), "
                "has_table_privilege(current_user, %s, 'TRUNCATE'), "
                "has_table_privilege(current_user, %s, 'TRIGGER')",
                [table] * 4,
            ).fetchone()
            assert row == (True, True, False, False)
            runtime.execute(sql.SQL("SELECT * FROM {} LIMIT 1").format(sql.Identifier(table)))
        for table in EVIDENCE:
            for privilege in ("UPDATE", "DELETE", "REFERENCES"):
                assert not runtime.execute(
                    "SELECT has_table_privilege(current_user, %s, %s)",
                    ["librarium_" + table, privilege],
                ).fetchone()[0]
        for table in MUTABLE:
            for privilege in ("UPDATE", "DELETE"):
                assert runtime.execute(
                    "SELECT has_table_privilege(current_user, %s, %s)",
                    ["librarium_" + table, privilege],
                ).fetchone()[0]
        for statement in (
            "TRUNCATE librarium_deliveryevent CASCADE",
            "DELETE FROM librarium_deliveryevent",
            "UPDATE librarium_deliveryevent SET payload = payload",
            "ALTER TABLE librarium_deliveryevent DISABLE TRIGGER ALL",
            "DROP TABLE librarium_deliveryevent CASCADE",
            "CREATE TABLE public.guard_unwanted(id integer)",
            "CREATE TEMP TABLE guard_unwanted(id integer)",
            "CREATE SCHEMA guard_unwanted",
            (
                "CREATE TRIGGER guard_unwanted BEFORE INSERT ON librarium_deliveryevent "
                "FOR EACH ROW EXECUTE FUNCTION librarium_delivery_immutable()"
            ),
            "SET session_replication_role = replica",
            "SET ROLE " + connection.ops.quote_name(connection.settings_dict["USER"]),
        ):
            with pytest.raises(psycopg.errors.InsufficientPrivilege):
                runtime.execute(statement)
        for privilege in ("SELECT", "INSERT", "TRUNCATE", "TRIGGER"):
            assert not runtime.execute(
                "SELECT has_table_privilege(current_user, 'librarium_guard_future', %s)",
                [privilege],
            ).fetchone()[0]
        # A real INSERT (and mutable job UPDATE) still works without function EXECUTE grants.
        runtime.execute(
            """INSERT INTO librarium_deliveryevent
            (id, payload, sha256, created_at, intent_id, job_id)
            SELECT %s, payload, sha256, now(), intent_id, job_id
            FROM librarium_deliveryevent LIMIT 1""",
            [uuid.uuid4()],
        )
        assert runtime.execute("UPDATE librarium_job SET message = message").rowcount > 0
    with connection.cursor() as cursor:
        cursor.execute("DROP TABLE librarium_guard_future")


@pytest.mark.django_db(transaction=True)
def test_transactional_flush_restores_guards():
    call_command("flush", interactive=False, verbosity=0)
    with connection.cursor() as cursor:
        cursor.execute(
            "SELECT tgenabled FROM pg_trigger WHERE tgname = 'librarium_evidence_no_truncate'"
        )
        guards = cursor.fetchall()
        assert guards and all(row[0] == "A" for row in guards)
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("TRUNCATE librarium_deliveryevent")


@pytest.mark.django_db(transaction=True)
def test_failed_flush_rolls_back_disabled_guards():
    statements = connection.ops.sql_flush(no_style(), list(TABLES), allow_cascade=True)
    with pytest.raises(DatabaseError):
        connection.ops.execute_sql_flush([*statements[:-1], "SELECT 1/0", statements[-1]])
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("TRUNCATE librarium_deliveryevent")


@pytest.mark.django_db
def test_recorded_owner_maintenance_and_rollback():
    with connection.cursor() as cursor:
        cursor.execute(
            "INSERT INTO librarium_evidence_maintenance(reason, tables) "
            "VALUES ('Disposable maintenance verification', ARRAY['librarium_deliveryevent'])"
        )
        cursor.execute(
            "ALTER TABLE librarium_deliveryevent DISABLE TRIGGER librarium_evidence_no_truncate"
        )
        cursor.execute("TRUNCATE librarium_deliveryevent")
        cursor.execute(
            "ALTER TABLE librarium_deliveryevent ENABLE ALWAYS TRIGGER librarium_evidence_no_truncate"
        )
        cursor.execute(
            "SELECT transaction_id = pg_current_xact_id() FROM librarium_evidence_maintenance"
        )
        assert all(row[0] for row in cursor.fetchall())
    with (
        pytest.raises(DatabaseError, match="append-only"),
        transaction.atomic(),
        connection.cursor() as cursor,
    ):
        cursor.execute("TRUNCATE librarium_deliveryevent")
    for statement in (
        "DELETE FROM librarium_evidence_maintenance",
        "UPDATE librarium_evidence_maintenance SET reason = 'Changed audit record'",
        "TRUNCATE librarium_evidence_maintenance",
    ):
        with (
            pytest.raises(DatabaseError, match="append-only"),
            transaction.atomic(),
            connection.cursor() as cursor,
        ):
            cursor.execute(statement)


@pytest.mark.django_db(transaction=True)
def test_production_flush_refuses_and_test_backend_cannot_flush_ordinary_database():
    from django.db.backends.postgresql.operations import DatabaseOperations

    operations = DatabaseOperations(connection)
    with pytest.raises(DatabaseError, match="append-only"):
        operations.execute_sql_flush(
            operations.sql_flush(no_style(), [*TABLES, "librarium_coversearch"])
        )
    original = connection.settings_dict["TEST"]["NAME"]
    try:
        connection.settings_dict["TEST"]["NAME"] = "librarium_guard_other"
        with pytest.raises(RuntimeError, match="restricted"):
            connection.ops.execute_sql_flush(["SELECT 1"])
    finally:
        connection.settings_dict["TEST"]["NAME"] = original


def test_runtime_rejects_membership_and_elevated_roles(runtime_role):
    from django.core.management.base import CommandError

    name, admin, _password = runtime_role
    admin.execute(sql.SQL("ALTER ROLE {} CREATEDB").format(sql.Identifier(name)))
    with pytest.raises(CommandError, match="elevated"):
        call_command("provision_runtime_role", name)
    admin.execute(sql.SQL("ALTER ROLE {} NOCREATEDB").format(sql.Identifier(name)))
    owner = connection.settings_dict["USER"]
    admin.execute(sql.SQL("GRANT {} TO {}").format(sql.Identifier(owner), sql.Identifier(name)))
    try:
        with pytest.raises(CommandError, match="memberships"):
            call_command("provision_runtime_role", name)
    finally:
        admin.execute(
            sql.SQL("REVOKE {} FROM {}").format(sql.Identifier(owner), sql.Identifier(name))
        )


@pytest.mark.parametrize("runtime", [False, True])
def test_runtime_database_credentials_are_separate(monkeypatch, runtime):
    import subprocess
    import sys

    monkeypatch.setenv("LIBRARIUM_SECRET_KEY", "test-only-" + "x" * 60)
    monkeypatch.setenv("PGUSER", "librarium_guard_owner")
    monkeypatch.setenv("PGPASSWORD", "test-owner-password")
    if runtime:
        monkeypatch.setenv("LIBRARIUM_RUNTIME_DB_USER", "librarium_guard_runtime")
        monkeypatch.setenv("LIBRARIUM_RUNTIME_DB_PASSWORD", "test-runtime-password")
    else:
        monkeypatch.delenv("LIBRARIUM_RUNTIME_DB_USER", raising=False)
        monkeypatch.delenv("LIBRARIUM_RUNTIME_DB_PASSWORD", raising=False)
    result = subprocess.run(
        [
            sys.executable,
            "-c",
            (
                "import librarium.settings as s; "
                "d = s.DATABASES['default']; import os; "
                "assert d['USER'] == os.getenv('LIBRARIUM_RUNTIME_DB_USER', os.environ['PGUSER']); "
                "assert d['PASSWORD'] == os.getenv('LIBRARIUM_RUNTIME_DB_PASSWORD', os.environ['PGPASSWORD']); "
                "assert d['ENGINE'] == 'django.db.backends.postgresql'"
            ),
        ],
        capture_output=True,
        text=True,
        check=False,
        env={**os.environ, "PYTHONPATH": "backend"},
    )
    assert result.returncode == 0, result.stderr


@pytest.mark.django_db
@pytest.mark.parametrize("table", (*TABLES, "librarium_evidence_maintenance"))
def test_owner_truncate_is_refused_in_replica_mode(table):
    params = connection.get_connection_params()
    for key in ("cursor_factory", "context", "prepare_threshold"):
        params.pop(key, None)
    params["user"] = os.environ.get("LIBRARIUM_TEST_ADMIN_USER", params.get("user"))
    with (
        psycopg.connect(**params) as admin,
        pytest.raises(psycopg.errors.RaiseException, match="append-only"),
        admin.transaction(),
    ):
        admin.execute("SET LOCAL session_replication_role = replica")
        admin.execute(
            sql.SQL("SET LOCAL ROLE {}").format(sql.Identifier(connection.settings_dict["USER"]))
        )
        admin.execute(sql.SQL("TRUNCATE {} CASCADE").format(sql.Identifier(table)))


def test_runtime_rejects_create_in_another_schema(runtime_role):
    from django.core.management.base import CommandError

    name, admin, _password = runtime_role
    admin.execute("CREATE SCHEMA librarium_guard_extra")
    try:
        admin.execute(
            sql.SQL("GRANT CREATE ON SCHEMA librarium_guard_extra TO {}").format(
                sql.Identifier(name)
            )
        )
        with pytest.raises(CommandError, match="other schemas"):
            call_command("provision_runtime_role", name)
    finally:
        admin.execute("DROP SCHEMA librarium_guard_extra")


@pytest.mark.django_db(transaction=True)
def test_rollback_restores_0009_only_while_no_maintenance_was_recorded():
    from django.db.migrations.executor import MigrationExecutor

    def guards():
        with connection.cursor() as cursor:
            cursor.execute(
                "SELECT count(*) FROM pg_trigger WHERE tgname = 'librarium_evidence_no_truncate'"
            )
            return cursor.fetchone()[0]

    leaf = MigrationExecutor(connection).loader.graph.leaf_nodes()
    try:
        MigrationExecutor(connection).migrate([("librarium", "0009_epub_delivery")])
        assert guards() == 0
        MigrationExecutor(connection).migrate(leaf)
        assert guards() > 0
        with connection.cursor() as cursor:
            cursor.execute(
                "INSERT INTO librarium_evidence_maintenance(reason, tables) "
                "VALUES ('Recorded guard maintenance', ARRAY['deliveryevent'])"
            )
        with pytest.raises(DatabaseError, match="maintenance history exists"):
            MigrationExecutor(connection).migrate([("librarium", "0009_epub_delivery")])
        assert guards() > 0
    finally:
        MigrationExecutor(connection).migrate(leaf)
