"""Types shared by every stage contract (00 §6).

- Coordinates are PDF points, origin top left after rotation, `[x0, y0, x1, y1]` (01 §6.4).
- IDs carry the prefix of 00 §6.1.
- Money and rates are `Decimal` in code and strings in JSON, never numbers (CLAUDE.md non-negotiable 5).
"""

from decimal import Decimal, InvalidOperation
from typing import Annotated, Any, Literal

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, PlainSerializer, WithJsonSchema


class Contract(BaseModel):
    """A stage boundary. Unknown fields are refused, so a producer and its consumer can't drift apart quietly."""

    model_config = ConfigDict(extra="forbid")


def _decimal_from_string(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if not isinstance(value, str):
        raise ValueError('a decimal must be sent as a string, e.g. "0.15"')
    try:
        return Decimal(value)
    except InvalidOperation as e:
        raise ValueError("not a decimal") from e


DecimalStr = Annotated[
    Decimal,
    BeforeValidator(_decimal_from_string),
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    WithJsonSchema({"type": "string", "pattern": r"^-?\d+(\.\d+)?$", "examples": ["0.15"]}),
]


def _quantity(value: Any) -> Decimal:
    if isinstance(value, bool):
        raise ValueError("a quantity is a number")
    if isinstance(value, int | float):
        return Decimal(str(value))  # str(), so 1.5 m stays exactly 1.5
    return _decimal_from_string(value)


# A quantity, not money: 07 §6.1's example sends it as a JSON number, so numbers are accepted. Written back as an
# exact decimal string, like the `numeric(12,3)` column.
QtyStr = Annotated[
    Decimal,
    BeforeValidator(_quantity),
    PlainSerializer(lambda d: format(d, "f"), return_type=str),
    WithJsonSchema({"type": ["string", "number"], "examples": ["4", "2.5"]}),
]


def _id(prefix: str) -> Any:
    """An ID with its 00 §6.1 prefix, e.g. `drw_01J…`. Fixtures in the specs use short forms like `pg_001`."""
    return Field(pattern=rf"^{prefix}_[0-9A-Za-z_]+$")


DrawingId = Annotated[str, _id("drw")]
FileId = Annotated[str, _id("fil")]
PageId = Annotated[str, _id("pg")]
PanelId = Annotated[str, _id("pnl")]
SpanId = Annotated[str, _id("ts")]
BlockId = Annotated[str, _id("blk")]
TileId = Annotated[str, _id("tl")]
DetId = Annotated[str, _id("det")]
InstanceId = Annotated[str, _id("ins")]
ComponentId = Annotated[str, _id("cmp")]
IssueId = Annotated[str, _id("iss")]
QuoteId = Annotated[str, _id("quo")]
LineId = Annotated[str, _id("ln")]
TraceId = Annotated[str, _id("trc")]
TenantId = Annotated[str, _id("tnt")]

Bbox = tuple[float, float, float, float]
Point = tuple[float, float]
Confidence = Annotated[float, Field(ge=0, le=1)]
Rotation = Literal[0, 90, 180, 270]
Severity = Literal["info", "warning", "error"]


class StageIssue(Contract):
    """A warning or error a stage reports about its input (01 §6.5). `message` is Hebrew, ready to show."""

    code: str
    severity: Severity
    page_id: PageId | None = None
    message: str
