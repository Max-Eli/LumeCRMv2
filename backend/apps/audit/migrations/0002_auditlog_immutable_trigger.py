"""Database-level append-only enforcement for the audit log.

HIPAA §164.312(b) (audit controls) requires a tamper-resistant record
of PHI access. `AuditLog` blocks UPDATE/DELETE in Python (`save()` /
`delete()`), but raw SQL, `QuerySet.update()`, and `bulk_*` bypass the
model layer entirely. This trigger enforces immutability in the
database itself: any UPDATE or DELETE on `audit_auditlog` raises.

`TRUNCATE` is intentionally NOT blocked — it fires a separate trigger
type, and Django's test-database flush relies on it.
"""

from django.db import migrations


_FORWARD = """
CREATE OR REPLACE FUNCTION audit_auditlog_immutable()
    RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION
        'audit_auditlog is append-only; % is not permitted', TG_OP;
END;
$$ LANGUAGE plpgsql;

CREATE TRIGGER audit_auditlog_no_update_delete
    BEFORE UPDATE OR DELETE ON audit_auditlog
    FOR EACH ROW EXECUTE FUNCTION audit_auditlog_immutable();
"""

_REVERSE = """
DROP TRIGGER IF EXISTS audit_auditlog_no_update_delete ON audit_auditlog;
DROP FUNCTION IF EXISTS audit_auditlog_immutable();
"""


class Migration(migrations.Migration):

    dependencies = [
        ('audit', '0001_initial'),
    ]

    operations = [
        migrations.RunSQL(sql=_FORWARD, reverse_sql=_REVERSE),
    ]
