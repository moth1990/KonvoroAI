"""Declarative base, shared column types and helpers for the models (docs/db-schema.md §1–2)."""

from collections.abc import Sequence
from datetime import datetime
from decimal import Decimal
from typing import Any, ClassVar

from sqlalchemy import (
    CheckConstraint,
    DateTime,
    ForeignKey,
    ForeignKeyConstraint,
    MetaData,
    Numeric,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Money, rates and quantities are always Decimal (00 §6.5, 07). Never float.
Money = Numeric(14, 4, asdecimal=True)
Rate = Numeric(7, 4, asdecimal=True)
Qty = Numeric(12, 3, asdecimal=True)

NAMING = {
    "ix": "ix_%(table_name)s_%(column_0_N_name)s",
    "uq": "uq_%(table_name)s_%(column_0_N_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_N_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING)
    type_annotation_map: ClassVar[dict[Any, Any]] = {
        str: Text(),
        dict[str, Any]: JSONB(),
        list[Any]: JSONB(),
        Decimal: Money,
        datetime: DateTime(timezone=True),
    }


class Created:
    created_at: Mapped[datetime] = mapped_column(server_default=func.now())


class Timestamps(Created):
    updated_at: Mapped[datetime] = mapped_column(server_default=func.now(), onupdate=func.now())


class TenantScoped:
    """Every tenant table: tenant_id, guarded by RLS in the migration (docs/db-schema.md §2)."""

    tenant_id: Mapped[str] = mapped_column(ForeignKey("tenants.id"))


def one_of(column: str, values: Sequence[str | int], name: str | None = None) -> CheckConstraint:
    """An enum as a CHECK constraint, so adding a value is a one-line migration."""
    listed = ", ".join(repr(v) if isinstance(v, str) else str(v) for v in values)
    return CheckConstraint(f"{column} IN ({listed})", name=name or column)


def tenant_fk(column: str, table: str, ondelete: str | None = None) -> ForeignKeyConstraint:
    """(tenant_id, column) -> table(tenant_id, id): a row can never point at another tenant's row."""
    return ForeignKeyConstraint(
        ["tenant_id", column],
        [f"{table}.tenant_id", f"{table}.id"],
        ondelete=ondelete,
    )


def tenant_unique() -> UniqueConstraint:
    """Target for tenant_fk on every tenant table that has an id."""
    return UniqueConstraint("tenant_id", "id")


def pk() -> Mapped[str]:
    return mapped_column(Text, primary_key=True)
