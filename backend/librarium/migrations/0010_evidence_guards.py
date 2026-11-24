"""PostgreSQL built-ins protect delivery history, including replication sessions."""

from django.db import migrations

EVIDENCE = (
    "deliveryintent",
    "deliveryapproval",
    "deliverytargetbinding",
    "deliveryevent",
    "deliveryreceipt",
    "undointent",
)

GUARDS = """
CREATE TABLE librarium_evidence_maintenance (
    id bigint GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    recorded_at timestamptz NOT NULL DEFAULT clock_timestamp(),
    transaction_id xid8 NOT NULL DEFAULT pg_current_xact_id(),
    actor name NOT NULL DEFAULT session_user,
    reason text NOT NULL CHECK (length(btrim(reason)) BETWEEN 8 AND 1000),
    tables text[] NOT NULL CHECK (cardinality(tables) > 0)
);
REVOKE ALL ON librarium_evidence_maintenance FROM PUBLIC;
CREATE TRIGGER immutable_evidence_maintenance
BEFORE UPDATE OR DELETE ON librarium_evidence_maintenance
FOR EACH ROW EXECUTE FUNCTION librarium_delivery_immutable();
ALTER TABLE librarium_evidence_maintenance ENABLE ALWAYS TRIGGER immutable_evidence_maintenance;
"""
for table in (*EVIDENCE, "deliverystate", "evidence_maintenance"):
    GUARDS += f"""
CREATE TRIGGER librarium_evidence_no_truncate BEFORE TRUNCATE ON librarium_{table}
FOR EACH STATEMENT EXECUTE FUNCTION librarium_delivery_immutable();
ALTER TABLE librarium_{table} ENABLE ALWAYS TRIGGER librarium_evidence_no_truncate;
"""
for table in EVIDENCE:
    GUARDS += f"ALTER TABLE librarium_{table} ENABLE ALWAYS TRIGGER immutable_{table};\n"

# Rolling back is owner-only schema maintenance and refuses once any guard
# maintenance has been recorded, so real maintenance history is never dropped.
REVERSE = """
DO $$
BEGIN
    IF EXISTS (SELECT 1 FROM librarium_evidence_maintenance) THEN
        RAISE EXCEPTION 'evidence maintenance history exists; guards stay installed';
    END IF;
END
$$;
"""
for table in EVIDENCE:
    REVERSE += f"ALTER TABLE librarium_{table} ENABLE TRIGGER immutable_{table};\n"
for table in (*EVIDENCE, "deliverystate"):
    REVERSE += f"DROP TRIGGER librarium_evidence_no_truncate ON librarium_{table};\n"
REVERSE += "DROP TABLE librarium_evidence_maintenance;\n"


class Migration(migrations.Migration):
    dependencies = [("librarium", "0009_epub_delivery")]

    operations = [migrations.RunSQL(GUARDS, reverse_sql=REVERSE)]
