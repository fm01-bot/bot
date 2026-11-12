"""add_giveaways

Revision ID: f1a2b3c4d5e6
Revises: a1b2c3d4e5f6
Create Date: 2026-11-12 00:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "f1a2b3c4d5e6"
down_revision: str | Sequence[str] | None = "a1b2c3d4e5f6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.create_table(
		"giveaways",
		sa.Column("id", sa.BigInteger(), sa.Identity(), primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("channel_id", sa.Numeric(), nullable=False),
		sa.Column("message_id", sa.Numeric(), nullable=True, unique=True),
		sa.Column("host_id", sa.Numeric(), nullable=False),
		sa.Column("prize", sa.Text(), nullable=False),
		sa.Column("winner_count", sa.Integer(), nullable=False),
		sa.Column("required_level", sa.Integer(), nullable=True),
		sa.Column("required_role_id", sa.Numeric(), nullable=True),
		sa.Column("required_messages", sa.Integer(), nullable=True),
		sa.Column("status", sa.Text(), nullable=False, server_default=sa.text("'active'")),
		sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("ends_at", sa.TIMESTAMP(timezone=True), nullable=False),
		sa.Column("ended_at", sa.TIMESTAMP(timezone=True), nullable=True),
		sa.CheckConstraint("status IN ('active', 'ended', 'cancelled')", name="ck_giveaways_status"),
		sa.CheckConstraint("winner_count > 0", name="ck_giveaways_winner_count"),
	)
	op.create_index("giveaways_channel_status_created_idx", "giveaways", ["channel_id", "status", "created_at"])
	op.create_index("giveaways_guild_status_idx", "giveaways", ["guild_id", "status"])

	op.create_table(
		"giveaway_entries",
		sa.Column(
			"giveaway_id",
			sa.BigInteger(),
			sa.ForeignKey("giveaways.id", ondelete="CASCADE"),
			primary_key=True,
		),
		sa.Column("user_id", sa.Numeric(), primary_key=True),
		sa.Column("joined_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("has_won", sa.Boolean(), nullable=False, server_default=sa.text("false")),
	)

	op.create_table(
		"giveaway_message_counts",
		sa.Column(
			"giveaway_id",
			sa.BigInteger(),
			sa.ForeignKey("giveaways.id", ondelete="CASCADE"),
			primary_key=True,
		),
		sa.Column("user_id", sa.Numeric(), primary_key=True),
		sa.Column("count", sa.Integer(), nullable=False, server_default=sa.text("0")),
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_table("giveaway_message_counts")
	op.drop_table("giveaway_entries")
	op.drop_index("giveaways_guild_status_idx", table_name="giveaways")
	op.drop_index("giveaways_channel_status_created_idx", table_name="giveaways")
	op.drop_table("giveaways")
