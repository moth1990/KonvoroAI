"""The master catalog loader against the database (docs/catalog-import.md)."""

from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.catalog import load, parse

FILE = "brand,sku,family,list_price,list_currency,status,replaced_by_sku,attr.current_a\n"


def test_a_rerun_updates_in_place(migrated_db: dict[str, Engine]) -> None:
    owner = migrated_db["owner"]
    with Session(owner) as s, s.begin():
        load(s, parse(FILE + "TST,T-OLD,relay,10,ILS,discontinued,T-NEW,\nTST,T-NEW,relay,12.5,EUR,,,16\n"))
    with Session(owner) as s:
        before = {i.sku: i for i in s.scalars(select(m.CatalogItem).where(m.CatalogItem.brand == "TST"))}
    assert before["T-OLD"].replaced_by == before["T-NEW"].id and before["T-OLD"].status == "discontinued"
    assert str(before["T-NEW"].list_price) == "12.5000" and before["T-NEW"].attributes == {"current_a": 16}
    assert before["T-NEW"].source == "import"

    with Session(owner) as s, s.begin():
        load(s, parse(FILE + "TST,T-OLD,relay,11,ILS,active,,\nTST,T-NEW,relay,12.5,EUR,,,16\n"))
    with Session(owner) as s:
        after = {i.sku: i for i in s.scalars(select(m.CatalogItem).where(m.CatalogItem.brand == "TST"))}
    assert {k: v.id for k, v in after.items()} == {k: v.id for k, v in before.items()}
    assert (str(after["T-OLD"].list_price), after["T-OLD"].status, after["T-OLD"].replaced_by) == (
        "11.0000",
        "active",
        None,
    )


def test_the_app_role_cannot_write_the_catalog(migrated_db: dict[str, Engine]) -> None:
    with Session(migrated_db["app"]) as s:
        try:
            load(s, parse("brand,sku,family\nTST,T-APP,relay\n"))
            s.commit()
            wrote = True
        except Exception:
            wrote = False
    assert wrote is False
