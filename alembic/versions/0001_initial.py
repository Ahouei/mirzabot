"""Initial schema - all legacy tables + rewrite additions.

Revision ID: 0001_initial
Revises:
Create Date: 2026-08-24
"""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import sqlalchemy as sa
from alembic import op

import mirza.models  # noqa: F401
import mirza.payments.wallet  # noqa: F401
from mirza.db import Base

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def upgrade() -> None:
    # JSONB is postgres-only; alembic renders the String variant on sqlite.
    for table in Base.metadata.sorted_tables:
        col_defs = []
        for column in table.columns:
            col = sa.Column(
                column.name,
                column.type,
                primary_key=column.primary_key,
                autoincrement=column.autoincrement,
                nullable=column.nullable,
                default=column.default,
                server_default=column.server_default,
            )
            col.table = table
            col_defs.append(col.compile(dialect=op.get_bind().dialect))
        table.create(bind=op.get_bind())


def downgrade() -> None:
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=op.get_bind())
