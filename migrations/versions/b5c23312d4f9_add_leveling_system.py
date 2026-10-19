"""add_leveling_system

Revision ID: b5c23312d4f9
Revises: fd185d92743c
Create Date: 2026-10-19 12:58:55.988659

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "b5c23312d4f9"
down_revision: str | Sequence[str] | None = "fd185d92743c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.create_table(
		"level_config",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("is_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("multiplier", sa.Float(), nullable=False, server_default=sa.text("1.0")),
		sa.Column("min_xp", sa.Integer(), nullable=False, server_default=sa.text("15")),
		sa.Column("max_xp", sa.Integer(), nullable=False, server_default=sa.text("25")),
		sa.Column("cooldown", sa.Integer(), nullable=False, server_default=sa.text("60")),
		sa.Column("message_mode", sa.Text(), nullable=False, server_default=sa.text("'current'::text")),
		sa.Column("levelup_message", sa.Text(), nullable=True),
		sa.Column("stack_roles", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.UniqueConstraint("guild_id", name="level_config_guild_pk"),
	)

	op.create_table(
		"user_levels",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("user_id", sa.Numeric(), nullable=False),
		sa.Column("xp", sa.BigInteger(), nullable=False, server_default=sa.text("0")),
		sa.Column("level", sa.Integer(), nullable=False, server_default=sa.text("0")),
		sa.Column("last_message_at", sa.TIMESTAMP(timezone=True), nullable=True),
		sa.UniqueConstraint("guild_id", "user_id", name="user_levels_guild_user_unique"),
	)
	op.create_index("user_levels_guild_xp_idx", "user_levels", ["guild_id", "xp"])

	op.create_table(
		"level_roles",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("level", sa.Integer(), nullable=False),
		sa.Column("role_id", sa.Numeric(), nullable=False),
		sa.UniqueConstraint("guild_id", "level", "role_id", name="level_roles_guild_level_role_unique"),
	)
	op.create_index("level_roles_guild_level_idx", "level_roles", ["guild_id", "level"])

	op.create_table(
		"level_channel_overrides",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("channel_id", sa.Numeric(), nullable=False),
		sa.Column("multiplier", sa.Float(), nullable=False, server_default=sa.text("1.0")),
		sa.Column("is_ignored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.UniqueConstraint("guild_id", "channel_id", name="level_channel_overrides_guild_channel_unique"),
	)

	op.create_table(
		"level_role_overrides",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("role_id", sa.Numeric(), nullable=False),
		sa.Column("multiplier", sa.Float(), nullable=False, server_default=sa.text("1.0")),
		sa.Column("is_ignored", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.UniqueConstraint("guild_id", "role_id", name="level_role_overrides_guild_role_unique"),
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_table("level_role_overrides")
	op.drop_table("level_channel_overrides")
	op.drop_table("level_roles")
	op.drop_index("user_levels_guild_xp_idx", table_name="user_levels")
	op.drop_table("user_levels")
	op.drop_table("level_config")
