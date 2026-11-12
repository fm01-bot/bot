"""unique_economy_account

Merges duplicate (guild_id, user_id) rows in ``economy`` (possible because nothing prevented concurrent inserts) by
summing their balances into the oldest row, then makes the pair unique so balance changes can upsert atomically.

Revision ID: 5e7a1c9d2b40
Revises: f1a2b3c4d5e6
Create Date: 2026-11-12 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "5e7a1c9d2b40"
down_revision: str | Sequence[str] | None = "f1a2b3c4d5e6"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""
	op.execute(
		"""
		WITH totals AS (
			SELECT MIN(id) AS keep_id, guild_id, user_id,
			       SUM(COALESCE(cash, 0)) AS cash, SUM(COALESCE(bank, 0)) AS bank
			FROM economy
			GROUP BY guild_id, user_id
			HAVING COUNT(*) > 1
		)
		UPDATE economy e SET cash = t.cash, bank = t.bank
		FROM totals t WHERE e.id = t.keep_id
		"""
	)
	op.execute(
		"""
		DELETE FROM economy e
		USING economy keep
		WHERE e.guild_id = keep.guild_id AND e.user_id = keep.user_id AND e.id > keep.id
		"""
	)
	op.execute("UPDATE economy SET cash = 0 WHERE cash IS NULL")
	op.execute("UPDATE economy SET bank = 0 WHERE bank IS NULL")
	op.alter_column("economy", "cash", existing_type=sa.Numeric(), nullable=False)
	op.alter_column("economy", "bank", existing_type=sa.Numeric(), nullable=False)
	op.create_unique_constraint("uq_economy_guild_user", "economy", ["guild_id", "user_id"])


def downgrade() -> None:
	"""Downgrade schema. Merged duplicate rows are not restored."""
	op.drop_constraint("uq_economy_guild_user", "economy", type_="unique")
	op.alter_column("economy", "bank", existing_type=sa.Numeric(), nullable=True)
	op.alter_column("economy", "cash", existing_type=sa.Numeric(), nullable=True)
