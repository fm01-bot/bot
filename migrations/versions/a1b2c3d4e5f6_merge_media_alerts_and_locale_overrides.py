"""merge_media_alerts_and_locale_overrides

Revision ID: a1b2c3d4e5f6
Revises: 04bf5d51578b, d8e9f01a2b3c
Create Date: 2026-11-11 00:00:00.000000

"""

from collections.abc import Sequence

# revision identifiers, used by Alembic.
revision: str = "a1b2c3d4e5f6"
down_revision: str | Sequence[str] | None = ("04bf5d51578b", "d8e9f01a2b3c")
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
	"""Upgrade schema."""


def downgrade() -> None:
	"""Downgrade schema."""
