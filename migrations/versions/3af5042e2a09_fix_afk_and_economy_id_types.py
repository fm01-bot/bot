"""fix_afk_and_economy_id_types

Revision ID: 3af5042e2a09
Revises: 9c2e1f4a5b6d
Create Date: 2026-10-23 14:30:09.873618

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "3af5042e2a09"
down_revision: str | Sequence[str] | None = "9c2e1f4a5b6d"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.alter_column(
		"afk",
		"user_id",
		existing_type=sa.Text(),
		type_=sa.Numeric(),
		existing_nullable=False,
		postgresql_using="user_id::numeric",
	)
	op.alter_column(
		"afk",
		"guild_id",
		existing_type=sa.Text(),
		type_=sa.Numeric(),
		existing_nullable=False,
		postgresql_using="guild_id::numeric",
	)
	op.alter_column(
		"economy",
		"guild_id",
		existing_type=sa.Text(),
		type_=sa.Numeric(),
		existing_nullable=False,
		postgresql_using="guild_id::numeric",
	)
	op.alter_column(
		"economy",
		"user_id",
		existing_type=sa.Text(),
		type_=sa.Numeric(),
		existing_nullable=False,
		postgresql_using="user_id::numeric",
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.alter_column(
		"economy",
		"user_id",
		existing_type=sa.Numeric(),
		type_=sa.Text(),
		existing_nullable=False,
		postgresql_using="user_id::text",
	)
	op.alter_column(
		"economy",
		"guild_id",
		existing_type=sa.Numeric(),
		type_=sa.Text(),
		existing_nullable=False,
		postgresql_using="guild_id::text",
	)
	op.alter_column(
		"afk",
		"guild_id",
		existing_type=sa.Numeric(),
		type_=sa.Text(),
		existing_nullable=False,
		postgresql_using="guild_id::text",
	)
	op.alter_column(
		"afk",
		"user_id",
		existing_type=sa.Numeric(),
		type_=sa.Text(),
		existing_nullable=False,
		postgresql_using="user_id::text",
	)
