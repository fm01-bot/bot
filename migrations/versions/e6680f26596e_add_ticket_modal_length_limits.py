"""add_ticket_modal_length_limits

Revision ID: e6680f26596e
Revises: 4f8e12b7a90c
Create Date: 2026-11-01 14:30:46.964796

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "e6680f26596e"
down_revision: str | Sequence[str] | None = "4f8e12b7a90c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.add_column(
		"ticket_config",
		sa.Column("topic_min_length", sa.Integer(), nullable=False, server_default=sa.text("3")),
	)
	op.add_column(
		"ticket_config",
		sa.Column("topic_max_length", sa.Integer(), nullable=False, server_default=sa.text("100")),
	)
	op.add_column(
		"ticket_config",
		sa.Column("description_min_length", sa.Integer(), nullable=False, server_default=sa.text("10")),
	)
	op.add_column(
		"ticket_config",
		sa.Column("description_max_length", sa.Integer(), nullable=False, server_default=sa.text("1800")),
	)


def downgrade() -> None:
	"""Downgrade schema."""
	op.drop_column("ticket_config", "description_max_length")
	op.drop_column("ticket_config", "description_min_length")
	op.drop_column("ticket_config", "topic_max_length")
	op.drop_column("ticket_config", "topic_min_length")
