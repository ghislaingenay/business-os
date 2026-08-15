"""add variant columns to files

Revision ID: 003
Revises: 002
Create Date: 2026-08-15 09:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

# revision identifiers, used by Alembic.
revision: str = "003"
down_revision: str | Sequence[str] | None = "002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("files", sa.Column("web_optimized_url", sa.String(512), nullable=True))
    op.add_column("files", sa.Column("thumbnail_url", sa.String(512), nullable=True))
    op.add_column("files", sa.Column("variants_processed_at", sa.TIMESTAMP(), nullable=True))


def downgrade() -> None:
    op.drop_column("files", "variants_processed_at")
    op.drop_column("files", "thumbnail_url")
    op.drop_column("files", "web_optimized_url")
