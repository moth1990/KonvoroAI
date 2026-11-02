"""The master catalog's CSV format (docs/catalog-import.md, S18 decision 1)."""

from decimal import Decimal

import pytest

from konboro.db.catalog import SAMPLE, CatalogFormatError, attribute, parse

HEADER = "brand,sku,family,list_price,list_currency,status,replaced_by_sku,module_width,attr.current_a,attr.poles\n"


def test_the_sample_parses() -> None:
    rows = parse(SAMPLE.read_text(encoding="utf-8"))
    assert len(rows) == 20 and {r.brand for r in rows} == {"ABB"}
    s203 = next(r for r in rows if r.sku == "S203M-C16")
    assert (s203.family, s203.list_price, s203.list_currency, s203.module_width) == (
        "circuit_breaker",
        Decimal("210.00"),
        "ILS",
        Decimal("3"),
    )
    assert s203.attributes == {"current_a": 16, "poles": 3, "curve": "C", "breaking_capacity_ka": 10, "neutral": False}
    ms116 = next(r for r in rows if r.sku == "MS116-6.3")
    assert ms116.attributes["range_max_a"] == 6.3 and "current_a" not in ms116.attributes
    # NURSERY-1's 3X20A is in the catalog, though the demo price list has no price for it (07 §7.2)
    assert any(r.sku == "S203M-C20" for r in rows)


def test_attribute_values() -> None:
    assert attribute("true") is True and attribute("false") is False
    assert attribute("16") == 16 and attribute("6.3") == 6.3
    assert attribute("1NO+1NC") == "1NO+1NC"


def test_defaults_and_bom() -> None:
    rows = parse("﻿brand,sku,family\nABB,X1,relay\n")
    assert rows[0].status == "active" and rows[0].list_price is None and rows[0].attributes == {}


def test_a_replacement_in_the_file() -> None:
    rows = parse(HEADER + "ABB,OLD,relay,,,discontinued,NEW,,,\nABB,NEW,relay,,,,,,,\n")
    assert rows[0].replaced_by_sku == "NEW" and rows[0].status == "discontinued"


def test_columns_are_checked_first() -> None:
    with pytest.raises(CatalogFormatError) as e:
        parse("brand,sku,price\nABB,X,1\n")
    assert e.value.errors == ["missing column 'family'", "unknown column 'price'"]


def test_every_row_problem_is_listed() -> None:
    body = (
        "ABB,,relay,,,,,,,\n"
        "ABB,X,relay,abc,ILS,,,,,\n"
        "ABB,X,relay,,,,,,,\n"
        "ABB,Y,relay,10,,,,,,\n"
        "ABB,Z,relay,10,ils,gone,,-1,,\n"
        "ABB,W,relay,NaN,ILS,,MISSING,,,\n"
    )
    with pytest.raises(CatalogFormatError) as e:
        parse(HEADER + body)
    assert e.value.errors == [
        "line 2: empty sku",
        "line 3: list_price 'abc' is not a number",
        "line 4: ABB X appears twice",
        "line 5: list_price needs list_currency",
        "line 6: status 'gone' is not one of active, discontinued",
        "line 6: list_currency 'ils' is not a 3-letter code",
        "line 6: module_width '-1' must be zero or more",
        "line 7: list_price 'NaN' must be zero or more",
        "ABB W: replaced_by_sku 'MISSING' is not in the file",
    ]
