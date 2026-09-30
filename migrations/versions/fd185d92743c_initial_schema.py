"""initial_schema

Revision ID: fd185d92743c
Revises:
Create Date: 2026-09-27 22:15:28.847005

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "fd185d92743c"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	op.create_table(
		"afk",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("user_id", sa.Text(), nullable=False),
		sa.Column("guild_id", sa.Text(), nullable=False),
		sa.Column("message", sa.Text(), nullable=False),
		sa.Column("state", sa.Boolean(), nullable=False),
		sa.Column("previous_nick", sa.Text(), nullable=False),
	)

	op.create_table(
		"economy",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Text(), nullable=False),
		sa.Column("user_id", sa.Text(), nullable=False),
		sa.Column("cash", sa.Numeric(), nullable=True, server_default=sa.text("0")),
		sa.Column("bank", sa.Numeric(), nullable=True, server_default=sa.text("0")),
	)

	op.create_table(
		"guilds",
		sa.Column("id", sa.Integer(), autoincrement=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False, primary_key=True),
		sa.Column("prefix", sa.Text(), nullable=True, server_default=sa.text("'?!'::text")),
		sa.Column("mention", sa.Boolean(), nullable=True, server_default=sa.text("true")),
		sa.Column("embed_colour", sa.Numeric(), nullable=True, server_default=sa.text("6656243")),
		sa.Column("global_ban_state", sa.Boolean(), nullable=True, server_default=sa.text("true")),
		sa.Column("global_ban_channel_id", sa.Numeric(), nullable=True),
	)

	op.create_table(
		"messages",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("payload", postgresql.JSON(astext_type=sa.Text()), nullable=True),
	)

	op.create_table(
		"shop",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("creator_id", sa.Numeric(), nullable=False),
		sa.Column("item_name", sa.Text(), nullable=False),
		sa.Column("item_description", sa.Text(), nullable=False),
		sa.Column("item_price", sa.Numeric(), nullable=False),
		sa.Column("role", sa.Numeric(), nullable=False),
	)

	op.create_table(
		"snapshots",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("name", sa.Text(), nullable=False),
		sa.Column("author_id", sa.Numeric(), nullable=False),
		sa.Column("date", sa.TIMESTAMP(timezone=True), nullable=False),
		sa.Column("code", sa.Text(), nullable=False),
		sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
	)

	op.create_table(
		"cases",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("type", sa.SmallInteger(), nullable=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("case_id", sa.Numeric(), nullable=True),
		sa.Column("user_id", sa.Numeric(), nullable=False),
		sa.Column("moderator_id", sa.Numeric(), nullable=False),
		sa.Column("reason", sa.Text(), nullable=True),
		sa.Column("expires", sa.TIMESTAMP(timezone=True), nullable=True),
		sa.Column("message", sa.Text(), nullable=True),
		sa.Column("created", sa.TIMESTAMP(timezone=True), nullable=True, server_default=sa.text("now()")),
	)

	op.create_table(
		"log",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("is_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("webhook", sa.Text(), nullable=True),
		sa.Column("channel", sa.Numeric(), nullable=True),
		sa.Column("modules", postgresql.ARRAY(sa.Text()), nullable=True, server_default=sa.text("ARRAY['*'::text]")),
		sa.Column(
			"channels", postgresql.JSONB(astext_type=sa.Text()), nullable=True, server_default=sa.text("'{}'::jsonb")
		),
		sa.UniqueConstraint("guild_id", name="log_pk"),
	)

	op.create_table(
		"join_config",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("is_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("channel", sa.Numeric(), nullable=True),
		sa.Column("message", sa.Text(), nullable=True),
		sa.UniqueConstraint("guild_id", name="join_config_guild_pk"),
	)

	op.create_table(
		"leave_config",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("is_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("channel", sa.Numeric(), nullable=True),
		sa.Column("message", sa.Text(), nullable=True),
		sa.UniqueConstraint("guild_id", name="leave_config_guild_pk"),
	)


def downgrade() -> None:
	op.drop_table("leave_config")
	op.drop_table("join_config")
	op.drop_table("log")
	op.drop_table("cases")
	op.drop_table("snapshots")
	op.drop_table("shop")
	op.drop_table("messages")
	op.drop_table("guilds")
	op.drop_table("economy")
	op.drop_table("afk")
