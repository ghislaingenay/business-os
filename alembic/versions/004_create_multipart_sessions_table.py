"""create multipart sessions table

Revision ID: 004
Revises: 003
Create Date: 2026-08-16 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "004"
down_revision: str | Sequence[str] | None = "003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "multipart_sessions",
        sa.Column(
            "upload_id",
            postgresql.UUID(as_uuid=True),
            primary_key=True,
            server_default=sa.text("gen_random_uuid()"),
        ),
        sa.Column("storage_upload_id", sa.String(255), nullable=False),
        sa.Column("filename", sa.String(255), nullable=False),
        sa.Column("size", sa.BigInteger(), nullable=False),
        sa.Column("mime_type", sa.String(127), nullable=False),
        sa.Column("part_size", sa.BigInteger(), nullable=False),
        sa.Column("total_parts", sa.Integer(), nullable=False),
        sa.Column("storage_key", sa.String(512), nullable=False),
        sa.Column(
            "finalized", sa.Boolean(), nullable=False, server_default=sa.text("FALSE")
        ),
        sa.Column(
            "created_at", sa.TIMESTAMP(), nullable=False, server_default=sa.text("NOW()")
        ),
        sa.Column("expires_at", sa.TIMESTAMP(), nullable=False),
        sa.CheckConstraint("size > 0", name="chk_multipart_size"),
        sa.CheckConstraint("total_parts > 0", name="chk_multipart_parts"),
    )

    op.create_index(
        "idx_multipart_sessions_expires",
        "multipart_sessions",
        ["expires_at"],
        postgresql_where=sa.text("NOT finalized"),
    )

    # Widen files.upload_strategy to admit the new multipart finalize path
    # (TD-005 §5) alongside the existing 'mediated'/'presigned' values.
    op.drop_constraint("chk_strategy", "files", type_="check")
    op.create_check_constraint(
        "chk_strategy", "files", "upload_strategy IN ('mediated', 'presigned', 'multipart')"
    )


def downgrade() -> None:
    op.drop_constraint("chk_strategy", "files", type_="check")
    op.create_check_constraint(
        "chk_strategy", "files", "upload_strategy IN ('mediated', 'presigned')"
    )
    op.drop_table("multipart_sessions")
