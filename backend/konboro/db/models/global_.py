"""Global layer: shared by every tenant, read-only for the app role (docs/db-schema.md §3)."""

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import ARRAY, CheckConstraint, ForeignKey, Numeric, Text, UniqueConstraint, text
from sqlalchemy.orm import Mapped, mapped_column

from ..base import Base, Created, Money, Rate, Timestamps, one_of, pk

GLOBAL_SOURCES = ("curated", "pilot_engineer", "import")


class KnowledgeSource:
    """Where a shared record came from (00 §14.2): curated by us, approved by the pilot engineer, or imported."""

    source: Mapped[str] = mapped_column(server_default="curated")
    source_tenant_id: Mapped[str | None]
    approved_by: Mapped[str | None]
    approved_at: Mapped[datetime | None]


class Plan(Base, Created):
    """Commercial packages (01 §4.3). `null` limits mean unlimited / counted with quotes."""

    __tablename__ = "plans"

    id: Mapped[str] = pk()
    name_he: Mapped[str]
    monthly_quote_limit: Mapped[int | None]
    monthly_audit_limit: Mapped[int | None]
    max_pages_per_file: Mapped[int] = mapped_column(server_default="30")
    active: Mapped[bool] = mapped_column(server_default=text("true"))


class FeatureFlag(Base, Created):
    """13 §2. A new flag is always off by default."""

    __tablename__ = "feature_flags"

    key: Mapped[str] = pk()
    description: Mapped[str]
    default_on: Mapped[bool] = mapped_column(server_default=text("false"))
    depends_on: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    owner: Mapped[str | None]
    remove_by: Mapped[date | None]


class PlanFeatureFlag(Base):
    __tablename__ = "plan_feature_flags"

    plan_id: Mapped[str] = mapped_column(ForeignKey("plans.id"), primary_key=True)
    flag_key: Mapped[str] = mapped_column(ForeignKey("feature_flags.key"), primary_key=True)
    enabled: Mapped[bool]


class AttributeSchema(Base, Timestamps):
    """05 §4.4: per family, which attributes exist and how they compare. current_a and poles never default."""

    __tablename__ = "attribute_schemas"

    family: Mapped[str] = pk()
    version: Mapped[int] = mapped_column(server_default="1")
    attributes: Mapped[list[Any]]


class CatalogItem(Base, Timestamps, KnowledgeSource):
    """The master catalog (05 §4.3, 07 §4.3)."""

    __tablename__ = "catalog_items"
    __table_args__ = (
        UniqueConstraint("brand", "sku"),
        one_of("status", ("active", "discontinued")),
        one_of("source", GLOBAL_SOURCES),
    )

    id: Mapped[str] = pk()
    sku: Mapped[str]
    brand: Mapped[str]
    series: Mapped[str | None]
    model_code: Mapped[str | None]
    family: Mapped[str]
    # The class within the family (`mcb`, `mccb`, `motor_protection`): stage 5 narrows by it (05 §5.1 item 2). Null
    # when the family has one class.
    symbol_class: Mapped[str | None]
    # The model codes as drawings write them ("S203M"; "XT1C160", "XT1C", "XT1"), upper case: an explicit series
    # narrows to the items that list it (05 §5.2.1). Migration 0015.
    model_tokens: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    attributes: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    module_width: Mapped[Decimal | None] = mapped_column(Numeric(5, 2))
    list_price: Mapped[Decimal | None] = mapped_column(Money)
    list_currency: Mapped[str | None]
    status: Mapped[str] = mapped_column(server_default="active")
    replaced_by: Mapped[str | None] = mapped_column(ForeignKey("catalog_items.id"))
    includes: Mapped[dict[str, Any] | None]
    # Per attribute, who set it when it was not the row's own source: `{name: {source, source_tenant_id, approved_by,
    # approved_at}}`, written by `konboro_promote` for a `catalog_attribute` candidate (00 §14.2, migration 0020).
    attribute_provenance: Mapped[dict[str, Any]] = mapped_column(server_default="{}")


class CatalogKit(Base, Created, KnowledgeSource):
    """05 §5.9.1: a main item and a part it needs, e.g. "XT1C … משולב פחת" is the breaker and its RCD module.
    `when_text` is the phrase in the component's text that calls for the part ("משולב פחת"); empty: always."""

    __tablename__ = "catalog_kits"
    __table_args__ = (
        UniqueConstraint("item_id", "part_id", "when_text"),
        CheckConstraint("quantity >= 1", name="quantity"),
        one_of("source", GLOBAL_SOURCES),
    )

    id: Mapped[str] = pk()
    item_id: Mapped[str] = mapped_column(ForeignKey("catalog_items.id", ondelete="CASCADE"))
    part_id: Mapped[str] = mapped_column(ForeignKey("catalog_items.id", ondelete="CASCADE"))
    quantity: Mapped[int] = mapped_column(server_default="1")
    when_text: Mapped[str] = mapped_column(server_default="")
    reason_he: Mapped[str]


class CatalogAccessory(Base, Created, KnowledgeSource):
    """05 §5.9.1: which accessory (an aux contact, a shunt trip, a lock) fits which device series of a brand."""

    __tablename__ = "catalog_accessories"
    __table_args__ = (UniqueConstraint("accessory_id", "fits_brand", "fits_series"), one_of("source", GLOBAL_SOURCES))

    id: Mapped[str] = pk()
    accessory_id: Mapped[str] = mapped_column(ForeignKey("catalog_items.id", ondelete="CASCADE"))
    fits_brand: Mapped[str]
    fits_series: Mapped[str]


class SymbolClass(Base, Created, KnowledgeSource):
    """03 §4.3."""

    __tablename__ = "symbol_classes"
    __table_args__ = (one_of("source", GLOBAL_SOURCES),)

    id: Mapped[str] = pk()
    family: Mapped[str]
    display_name_he: Mapped[str]
    billable: Mapped[bool]
    standard_ref: Mapped[str | None]
    attribute_schema: Mapped[str | None] = mapped_column(ForeignKey("attribute_schemas.family"))


class ReferenceCrop(Base, Created):
    """Global-scope reference crops (03 §4.3). The embedding column arrives with the similarity index (phase 4)."""

    __tablename__ = "reference_crops"
    __table_args__ = (one_of("source", ("curated", "user_correction", "legend", "pilot_engineer")),)

    id: Mapped[str] = pk()
    symbol_class: Mapped[str] = mapped_column(ForeignKey("symbol_classes.id"))
    image_key: Mapped[str]
    source: Mapped[str]
    source_tenant_id: Mapped[str | None]
    approved_count: Mapped[int] = mapped_column(server_default="0")


class Abbreviation(Base, Created, KnowledgeSource):
    """Global abbreviation dictionary ("מ.פ." = RCD), 03 §4.6."""

    __tablename__ = "abbreviations"
    __table_args__ = (UniqueConstraint("text"), one_of("source", GLOBAL_SOURCES))

    id: Mapped[str] = pk()
    text: Mapped[str]
    symbol_class: Mapped[str | None] = mapped_column(ForeignKey("symbol_classes.id"))
    family: Mapped[str | None]
    display_he: Mapped[str | None]


class SpellingPattern(Base, Created, KnowledgeSource):
    """A way designers write something, and what it means ("SAVE" is a spare circuit; "INC=" is the load current), 04
    §11. Only the pilot queue writes it so far (S24); stage 4 reads its grammar from `association/grammar.json`."""

    __tablename__ = "spelling_patterns"
    __table_args__ = (UniqueConstraint("pattern"), one_of("source", GLOBAL_SOURCES))

    id: Mapped[str] = pk()
    pattern: Mapped[str]
    meaning_he: Mapped[str]
    family: Mapped[str | None]
    attribute: Mapped[str | None]


class ValidatorRule(Base, Created):
    """06 §6.2: rules are data, versioned."""

    __tablename__ = "validator_rules"
    __table_args__ = (
        one_of("category", ("A", "B", "C", "D", "E")),
        one_of("severity", ("error", "warning", "info")),
        CheckConstraint(
            "requires IS NULL OR requires IN ('wire_graph', 'bom_table', 'front_view', 'text_layer')", name="requires"
        ),
    )

    rule_id: Mapped[str] = mapped_column(primary_key=True)
    version: Mapped[int] = mapped_column(primary_key=True)
    category: Mapped[str]
    applies_to: Mapped[list[str]] = mapped_column(ARRAY(Text), server_default="{}")
    requires: Mapped[str | None]
    severity: Mapped[str]
    params: Mapped[dict[str, Any]] = mapped_column(server_default="{}")
    message_he: Mapped[str]
    title_he: Mapped[str] = mapped_column(server_default="")
    enabled: Mapped[bool] = mapped_column(server_default=text("true"))
    approval: Mapped[str | None]  # `pending_expert`: category A until the electrical expert signs it off (S21)


class VatRate(Base, Created):
    """07 §4.3: VAT is data with a start date, never a constant in code."""

    __tablename__ = "vat_rates"
    __table_args__ = (UniqueConstraint("valid_from"),)

    id: Mapped[str] = pk()
    rate: Mapped[Decimal] = mapped_column(Rate)
    valid_from: Mapped[date]


class FxRate(Base, Created):
    __tablename__ = "fx_rates"

    currency: Mapped[str] = mapped_column(primary_key=True)
    rate_date: Mapped[date] = mapped_column(primary_key=True)
    rate: Mapped[Decimal] = mapped_column(Numeric(14, 6))
    source: Mapped[str]
