"""Persistence/ORM models for the upload domain (TD-002 Data Model)."""

import uuid
from datetime import datetime

from sqlalchemy import BigInteger, CheckConstraint, Index, String, text
from sqlalchemy.dialects.postgresql import UUID
from sqlalchemy.orm import Mapped, mapped_column
from sqlalchemy.sql import func

from database import Base


class File(Base):
    """A file whose bytes have been committed to storage (either upload path)."""

    __tablename__ = "files"
    __table_args__ = (
        CheckConstraint("size > 0", name="chk_size_positive"),
        CheckConstraint("upload_strategy IN ('mediated', 'presigned')", name="chk_strategy"),
        Index("idx_files_storage_key", "storage_key"),
        Index(
            "idx_files_sha256_hash",
            "sha256_hash",
            postgresql_where="sha256_hash IS NOT NULL",
        ),
        Index("idx_files_created_at", text("created_at DESC")),
    )

    file_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    sha256_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    etag: Mapped[str | None] = mapped_column(String(255), nullable=True)
    upload_strategy: Mapped[str] = mapped_column(String(20), nullable=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
    updated_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())


class UploadSession(Base):
    """Tracks a presigned-URL upload from initiation through finalization."""

    __tablename__ = "upload_sessions"
    __table_args__ = (
        CheckConstraint("size > 0", name="chk_session_size_positive"),
        Index(
            "idx_upload_sessions_expires_at",
            "expires_at",
            postgresql_where="NOT finalized",
        ),
        Index("idx_upload_sessions_finalized", "finalized", "created_at"),
    )

    upload_id: Mapped[uuid.UUID] = mapped_column(
        UUID(as_uuid=True), primary_key=True, server_default=func.gen_random_uuid()
    )
    filename: Mapped[str] = mapped_column(String(255), nullable=False)
    size: Mapped[int] = mapped_column(BigInteger, nullable=False)
    mime_type: Mapped[str] = mapped_column(String(127), nullable=False)
    presigned_url: Mapped[str] = mapped_column(nullable=False)
    storage_key: Mapped[str] = mapped_column(String(512), nullable=False)
    expires_at: Mapped[datetime] = mapped_column(nullable=False)
    finalized: Mapped[bool] = mapped_column(nullable=False, default=False)
    created_at: Mapped[datetime] = mapped_column(nullable=False, server_default=func.now())
