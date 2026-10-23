"""add_message_channel_to_level_config

Revision ID: 7bf3922376dd
Revises: b5c23312d4f9
Create Date: 2026-10-21 00:54:40.188466

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "7bf3922376dd"
down_revision: str | Sequence[str] | None = "b5c23312d4f9"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.add_column("level_config", sa.Column("message_channel", sa.Numeric(), nullable=True))


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_column("level_config", "message_channel")
