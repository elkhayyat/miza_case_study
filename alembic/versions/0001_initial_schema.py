"""initial schema

Revision ID: 0001
Revises:
Create Date: 2026-03-04 00:00:00.000000

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0001"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # investment_events
    op.create_table(
        "investment_events",
        sa.Column("event_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=False),
        sa.Column("event_type", sa.Enum("ALLOCATION", "REDEMPTION", "TRANSFER", "VALUATION_UPDATE", name="event_type_enum"), nullable=False),
        sa.Column("portfolio_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=False),
        sa.Column("asset_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=False),
        sa.Column("asset_class", sa.Enum("PRIVATE_EQUITY", "REAL_ESTATE", "HEDGE_FUND", "FIXED_INCOME", "EQUITY", name="asset_class_enum"), nullable=False),
        sa.Column("amount", sa.Numeric(20, 6), nullable=False),
        sa.Column("currency", sa.String(3), nullable=False),
        sa.Column("fx_rate_to_sar", sa.Numeric(12, 6), nullable=False),
        sa.Column("metadata", sa.JSON(), nullable=True),
        sa.Column("status", sa.Enum("PENDING", "PROCESSED", "FAILED", name="event_status_enum"), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("ingested_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("event_id"),
        sa.CheckConstraint("amount > 0", name="ck_amount_positive"),
    )
    op.create_index("ix_investment_events_portfolio_id", "investment_events", ["portfolio_id"])
    op.create_index("ix_investment_events_asset_class", "investment_events", ["asset_class"])
    op.create_index("ix_investment_events_event_type", "investment_events", ["event_type"])
    op.create_index("ix_investment_events_created_at", "investment_events", ["created_at"])
    op.create_index("ix_investment_events_portfolio_asset_class", "investment_events", ["portfolio_id", "asset_class"])

    # audit_logs
    op.create_table(
        "audit_logs",
        sa.Column("log_id", sa.Uuid(as_uuid=True, native_uuid=True), nullable=False),
        sa.Column("request_id", sa.String(36), nullable=False),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("entity_type", sa.String(64), nullable=False),
        sa.Column("entity_id", sa.String(36), nullable=True),
        sa.Column("api_key_id", sa.String(128), nullable=False),
        sa.Column("payload_hash", sa.String(64), nullable=True),
        sa.Column("ip_address", sa.String(45), nullable=False),
        sa.Column("timestamp", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("log_id"),
    )
    op.create_index("ix_audit_logs_request_id", "audit_logs", ["request_id"], unique=True)
    op.create_index("ix_audit_logs_api_key_id", "audit_logs", ["api_key_id"])
    op.create_index("ix_audit_logs_timestamp", "audit_logs", ["timestamp"])
    op.create_index("ix_audit_logs_action", "audit_logs", ["action"])


def downgrade() -> None:
    op.drop_table("audit_logs")
    op.drop_table("investment_events")
    op.execute("DROP TYPE IF EXISTS event_status_enum")
    op.execute("DROP TYPE IF EXISTS asset_class_enum")
    op.execute("DROP TYPE IF EXISTS event_type_enum")
