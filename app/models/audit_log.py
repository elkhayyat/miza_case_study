import uuid
from datetime import datetime

from sqlalchemy import DateTime, Index, String, Uuid
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from app.db.base import Base


class AuditLog(Base):
    """
    Append-only audit table for CMA compliance.
    No UPDATE or DELETE operations should ever be performed on this table.
    """

    __tablename__ = "audit_logs"

    log_id: Mapped[uuid.UUID] = mapped_column(
        Uuid(as_uuid=True, native_uuid=True), primary_key=True, default=uuid.uuid4
    )
    request_id: Mapped[str] = mapped_column(String(36), nullable=False)
    action: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str | None] = mapped_column(String(36), nullable=True)
    api_key_id: Mapped[str] = mapped_column(String(128), nullable=False)
    payload_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    ip_address: Mapped[str] = mapped_column(String(45), nullable=False)
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )

    __table_args__ = (
        Index("ix_audit_logs_request_id", "request_id"),
        Index("ix_audit_logs_api_key_id", "api_key_id"),
        Index("ix_audit_logs_timestamp", "timestamp"),
        Index("ix_audit_logs_action", "action"),
    )
