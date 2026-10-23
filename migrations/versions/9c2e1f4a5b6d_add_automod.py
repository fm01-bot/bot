"""add_automod

Revision ID: 9c2e1f4a5b6d
Revises: 7bf3922376dd
Create Date: 2026-10-23 13:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "9c2e1f4a5b6d"
down_revision: str | Sequence[str] | None = "7bf3922376dd"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.create_table(
		"automod_config",
		sa.Column("guild_id", sa.Numeric(), nullable=False, primary_key=True),
		sa.Column("is_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column(
			"settings", postgresql.JSONB(astext_type=sa.Text()), nullable=False, server_default=sa.text("'{}'::jsonb")
		),
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_table("automod_config")
