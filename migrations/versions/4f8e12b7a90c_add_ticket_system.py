"""add_ticket_system

Revision ID: 4f8e12b7a90c
Revises: 3af5042e2a09
Create Date: 2026-10-27 14:30:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "4f8e12b7a90c"
down_revision: str | Sequence[str] | None = "3af5042e2a09"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.create_table(
		"ticket_config",
		sa.Column("guild_id", sa.Numeric(), nullable=False, primary_key=True),
		sa.Column("is_on", sa.Boolean(), nullable=False, server_default=sa.text("true")),
		sa.Column("category_id", sa.Numeric(), nullable=True),
		sa.Column("log_channel_id", sa.Numeric(), nullable=True),
		sa.Column("support_role_id", sa.Numeric(), nullable=True),
		sa.Column("max_tickets", sa.Integer(), nullable=False, server_default=sa.text("1")),
		sa.Column("dm_transcript", sa.Boolean(), nullable=False, server_default=sa.text("true")),
	)

	op.create_table(
		"tickets",
		sa.Column("id", sa.Integer(), autoincrement=True, primary_key=True),
		sa.Column("guild_id", sa.Numeric(), nullable=False),
		sa.Column("channel_id", sa.Numeric(), nullable=False),
		sa.Column("user_id", sa.Numeric(), nullable=False),
		sa.Column("title", sa.Text(), nullable=False),
		sa.Column("description", sa.Text(), nullable=False),
		sa.Column("is_archived", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("is_closed", sa.Boolean(), nullable=False, server_default=sa.text("false")),
		sa.Column("created_at", sa.TIMESTAMP(timezone=True), nullable=False, server_default=sa.text("now()")),
		sa.Column("closed_at", sa.TIMESTAMP(timezone=True), nullable=True),
		sa.Column("closed_by", sa.Numeric(), nullable=True),
		sa.Column("transcript_path", sa.Text(), nullable=True),
	)
	op.create_index("tickets_guild_user_idx", "tickets", ["guild_id", "user_id"])
	op.create_index("tickets_channel_idx", "tickets", ["channel_id"])


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_index("tickets_channel_idx", table_name="tickets")
	op.drop_index("tickets_guild_user_idx", table_name="tickets")
	op.drop_table("tickets")
	op.drop_table("ticket_config")
