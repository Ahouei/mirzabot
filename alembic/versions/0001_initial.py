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
        table.create(bind=op.get_bind())
    # legacy compatibility view: old PHP read flat columns from `setting`;
    # the rewrite stores KV rows. Expose a KV-shaped view under the legacy
    # expected helper names so imported data stays readable either way.
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "CREATE OR REPLACE VIEW setting_legacy AS "
            "SELECT key, value FROM setting")
    else:
        op.execute(
            "CREATE VIEW IF NOT EXISTS setting_legacy AS "
            "SELECT key, value FROM setting")


def downgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute("DROP VIEW IF EXISTS setting_legacy")
    else:
        op.execute("DROP VIEW IF EXISTS setting_legacy")
    for table in reversed(Base.metadata.sorted_tables):
        table.drop(bind=op.get_bind())
