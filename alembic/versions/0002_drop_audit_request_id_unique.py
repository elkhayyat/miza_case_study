"""Drop unique constraint on audit_logs.request_id

Revision ID: 0002
Revises: 0001
Create Date: 2026-03-10 00:00:00.000000

"""

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_audit_logs_request_id", table_name="audit_logs")
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=True)
