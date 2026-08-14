"""create files table

Revision ID: 001
Revises:
Create Date: 2026-08-13 11:48:38.214606

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute('CREATE EXTENSION IF NOT EXISTS "pgcrypto"')

    op.create_table(
        "files",
        sa.Column(
            "file_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("sha256_hash", sa.String(64), nullable=True),
        sa.Column("etag", sa.String(255), nullable=True),
        sa.Column("upload_strategy", sa.String(20), nullable=False),
        sa.Column(
            "created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.Column(
            "updated_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.CheckConstraint("size > 0", name="chk_size_positive"),
        sa.CheckConstraint(
            "upload_strategy IN ('mediated', 'presigned')", name="chk_strategy"
        ),
    )

    op.create_index("idx_files_storage_key", "files", ["storage_key"])
    op.create_index(
        "idx_files_sha256_hash",
        "files",
        ["sha256_hash"],
        postgresql_where=sa.text("sha256_hash IS NOT NULL"),
    )
    op.create_index(
        "idx_files_created_at", "files", [sa.text("created_at DESC")]
    )


def downgrade() -> None:
    op.drop_table("files")
