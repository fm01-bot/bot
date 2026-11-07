"""add_media_alerts

Revision ID: d8e9f01a2b3c
Revises: e6680f26596e
Create Date: 2026-11-01 15:10:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "d8e9f01a2b3c"
down_revision: str | Sequence[str] | None = "e6680f26596e"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.create_table(
		"media_alerts",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("platform", sa.Text(), nullable=False),
		sa.Column("channel_account", sa.Text(), nullable=False),
		sa.Column("account_id", sa.Text(), nullable=True),
		sa.Column("account_name", sa.Text(), nullable=True),
		sa.Column("target_channel_id", sa.Numeric(), nullable=False),
		sa.Column("is_enabled", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("last_media_id", sa.Text(), nullable=True),
		sa.Column("last_media_time", sa.TIMESTAMP(timezone=True), nullable=True),
		sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.UniqueConstraint(
			"guild_id", "platform", "channel_account", "target_channel_id", name="uq_media_alerts_target"
		),
	)
	op.create_index(
		"ix_media_alerts_platform_account",
		"media_alerts",
		["platform", "channel_account"],
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_index("ix_media_alerts_platform_account", table_name="media_alerts")
	op.drop_table("media_alerts")
