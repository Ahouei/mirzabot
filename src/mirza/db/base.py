"""SQLAlchemy 2.x async declarative base + naming convention for Alembic.

JSONType: JSONB on PostgreSQL (production), portable TEXT+JSON serializer
variant on SQLite (tests/dev) so dict values bind correctly everywhere.
"""
from __future__ import annotations

import json

from sqlalchemy import MetaData, String, TypeDecorator
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase

NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class PortableJSON(TypeDecorator):
    """JSONB on PG; TEXT with json (de)serialization elsewhere."""

    impl = String
    cache_ok = True

    def load_dialect_impl(self, dialect):
        if dialect.name == "postgresql":
            return dialect.type_descriptor(JSONB())
        return dialect.type_descriptor(String())

    def process_bind_param(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        return json.dumps(value, ensure_ascii=False)

    def process_result_value(self, value, dialect):
        if value is None or dialect.name == "postgresql":
            return value
        try:
            return json.loads(value)
        except (ValueError, TypeError):
            return value


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)
    type_annotation_map = {
        # keep explicit column types working; JSON handled via models import
    }
