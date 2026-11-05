"""add_guild_locale_overrides

Revision ID: 04bf5d51578b
Revises: c7d8e9f01a2b
Create Date: 2026-11-05 17:01:37.782598

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "04bf5d51578b"
down_revision: str | Sequence[str] | None = "c7d8e9f01a2b"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.create_table(
		"guild_locale_overrides",
		sa.Column("guild_id", sa.Numeric(), nullable=False, primary_key=True),
		sa.Column("locale", sa.Text(2), nullable=False),
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_table("guild_locale_overrides")
