"""Change asset_id from UUID to VARCHAR(20) for ticker/ISIN identifiers.

Revision ID: 0004
Revises: 0003
Create Date: 2026-03-10 14:00:00.000000
"""

import sqlalchemy as sa

from alembic import op

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column(
        "investment_events",
        "asset_id",
        existing_type=sa.Uuid(),
        type_=sa.String(20),
        existing_nullable=False,
        postgresql_using="asset_id::text",
    )


def downgrade() -> None:
    op.alter_column(
        "investment_events",
        "asset_id",
        existing_type=sa.String(20),
        type_=sa.Uuid(),
        existing_nullable=False,
        postgresql_using="asset_id::uuid",
    )
