"""Add tamper-protection trigger to audit_logs.

PostgreSQL-only: SQLite does not support this trigger syntax.
The trigger raises an exception on any UPDATE or DELETE attempt,
enforcing the append-only CMA compliance requirement at the database level.

Revision ID: 0003
Revises: 0002
Create Date: 2026-03-10 12:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TRIGGER_FUNCTION = """\
CREATE OR REPLACE FUNCTION audit_logs_immutable()
RETURNS TRIGGER AS $$
BEGIN
    RAISE EXCEPTION 'audit_logs table is append-only: % operations are forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;
"""

CREATE_TRIGGER = """\
CREATE TRIGGER trg_audit_logs_immutable
    BEFORE UPDATE OR DELETE ON audit_logs
    FOR EACH ROW
    EXECUTE FUNCTION audit_logs_immutable();
"""

DROP_TRIGGER = "DROP TRIGGER IF EXISTS trg_audit_logs_immutable ON audit_logs;"
DROP_FUNCTION = "DROP FUNCTION IF EXISTS audit_logs_immutable();"


def upgrade() -> None:
    op.execute(TRIGGER_FUNCTION)
    op.execute(CREATE_TRIGGER)


def downgrade() -> None:
    op.execute(DROP_TRIGGER)
    op.execute(DROP_FUNCTION)
