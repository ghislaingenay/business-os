"""create upload sessions table

Revision ID: 002
Revises: 001
Create Date: 2026-08-13 11:53:40.077551

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "upload_sessions",
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("presigned_url", sa.Text(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.Column(
            "finalized", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.CheckConstraint("size > 0", name="chk_session_size_positive"),
    )

    op.create_index(
        "idx_upload_sessions_expires_at",
        "upload_sessions",
        ["expires_at"],
        postgresql_where=sa.text("NOT finalized"),
    )
    op.create_index(
        "idx_upload_sessions_finalized", "upload_sessions", ["finalized", "created_at"]
    )


def downgrade() -> None:
    op.drop_table("upload_sessions")
