"""`compare` with another quote (08 §6.5, S25b): lines pair by signature, then SKU, then description."""

from dataclasses import dataclass
from decimal import Decimal

from konboro.chat.compare import changed, key_of, pair


@dataclass
class L:
    id: str
    position: int
    signature: str | None
    sku: str | None
    qty: Decimal = Decimal(1)
    unit_price: Decimal | None = Decimal(10)
    line_total: Decimal | None = Decimal(10)
    manufacturer: str | None = "ABB"
    description: str = "שורה"
    line_type: str = "component"


def test_a_line_pairs_by_signature_though_its_sku_and_id_differ():
    before = [L("a1", 1, "cb|mcb|16|3", "S203M-C16")]
    after = [L("b1", 1, "cb|mcb|16|3", "A9F74316", manufacturer="Schneider Electric")]
    [p] = pair(before, after)
    assert (p.change, p.before, p.after) == ("changed", before[0], after[0])
    assert p.fields == ("sku", "manufacturer")


def test_within_a_signature_the_same_sku_pairs_first():
    before = [L("a1", 1, "dev", "X"), L("a2", 2, "dev", "Y")]
    after = [L("b1", 1, "dev", "Y"), L("b2", 2, "dev", "X")]
    pairs = pair(before, after)
    assert [(p.before.id, p.after.id) for p in pairs if p.before and p.after] == [("a2", "b1"), ("a1", "b2")]
    assert changed(pairs) == []


def test_a_line_without_a_signature_pairs_by_sku_then_description():
    assert key_of(L("a", 1, None, " ab-1 ")) == ("sku", "AB-1")
    assert key_of(L("a", 1, None, None, description="ארון  פח")) == ("description", "ארון פח")
    before = [L("a1", 1, None, "KIT-1"), L("a2", 2, None, None, description="עבודה")]
    after = [
        L("b1", 1, None, "KIT-1", qty=Decimal(2), line_total=Decimal(20)),
        L("b2", 2, None, None, description="עבודה"),
    ]
    pairs = changed(pair(before, after))
    assert [(p.change, p.fields) for p in pairs] == [("changed", ("qty",))]
    assert pairs[0].difference == Decimal(10)


def test_added_and_removed_lines_and_an_unknown_difference():
    before = [L("a1", 1, "old", "O"), L("a2", 2, "same", "S", line_total=None)]
    after = [L("b1", 1, "new", "N"), L("b2", 2, "same", "S", line_total=None)]
    pairs = changed(pair(before, after))
    assert [(p.change, (p.before or p.after).id) for p in pairs] == [("added", "b1"), ("removed", "a1")]
    assert pairs[0].difference == Decimal(10) and pairs[1].difference == Decimal(-10)
    assert pair(before, after)[1].difference is None  # a side with no price: unknown, never zero
    assert (
        Decimal("4") == Decimal("4.000")
        and changed(pair([L("a", 1, "s", "S", qty=Decimal("4.000"))], [L("b", 1, "s", "S", qty=Decimal(4))])) == []
    )
