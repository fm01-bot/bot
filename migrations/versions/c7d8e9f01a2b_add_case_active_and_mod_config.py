"""add_case_active_and_mod_config

Revision ID: c7d8e9f01a2b
Revises: e6680f26596e
Create Date: 2026-11-05 15:45:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "c7d8e9f01a2b"
down_revision: str | Sequence[str] | None = "e6680f26596e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.add_column(
		"cases",
		sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
	)
	op.create_table(
		"mod_config",
		sa.Column("guild_id", sa.Numeric(), nullable=False, primary_key=True),
		sa.Column("case_retention", sa.Enum("keep", "delete"), nullable=False, server_default=sa.text("'keep'::text")),
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_table("mod_config")
	op.drop_column("cases", "active")
