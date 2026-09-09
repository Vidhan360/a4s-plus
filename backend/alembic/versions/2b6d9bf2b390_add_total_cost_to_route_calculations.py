"""Add route_calculations.total_cost

The A* search minimises a weighted cost that was previously only visible in the
API response. Persisting it lets the UI (and the optimality check) compare
stored SAFEST vs SHORTEST calculations without re-running the search.

Revision ID: 2b6d9bf2b390
Revises: 45d83b6b3424
Create Date: 2026-09-09
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "2b6d9bf2b390"
down_revision = "45d83b6b3424"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "route_calculations",
        sa.Column("total_cost", sa.Float(), nullable=False, server_default="0"),
    )
    op.alter_column("route_calculations", "total_cost", server_default=None)


def downgrade() -> None:
    op.drop_column("route_calculations", "total_cost")
