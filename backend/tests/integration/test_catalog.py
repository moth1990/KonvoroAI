"""The master catalog loader against the database (docs/catalog-import.md)."""

import pytest
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.catalog import CatalogFormatError, load, parse, parse_accessories, parse_kits

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


def test_kits_and_accessories_load_and_rerun(migrated_db: dict[str, Engine]) -> None:
    """05 §5.9.1: a kit's part and an accessory's series, by brand and sku; a rerun changes nothing."""
    owner = migrated_db["owner"]
    items = parse("brand,sku,family,series\nTKT,MAIN,circuit_breaker,X\nTKT,PART,accessory,X\nTKT,AUX,aux_contact,\n")
    kits = parse_kits("brand,item_sku,part_sku,quantity,when_text,reason_he\nTKT,MAIN,PART,1,משולב פחת,מודול\n")
    fits = parse_accessories("brand,accessory_sku,fits_brand,fits_series\nTKT,AUX,TKT,X\n")
    for _ in range(2):
        with Session(owner) as s, s.begin():
            load(s, items, kits, fits)
    with Session(owner) as s:
        ids = {i.sku: i.id for i in s.scalars(select(m.CatalogItem).where(m.CatalogItem.brand == "TKT"))}
        kit = s.scalars(select(m.CatalogKit).where(m.CatalogKit.item_id == ids["MAIN"])).all()
        acc = s.scalars(select(m.CatalogAccessory).where(m.CatalogAccessory.accessory_id == ids["AUX"])).all()
    assert [(k.part_id, k.when_text, k.quantity) for k in kit] == [(ids["PART"], "משולב פחת", 1)]
    assert [(a.fits_brand, a.fits_series) for a in acc] == [("TKT", "X")]


def test_a_kit_naming_an_unknown_item_loads_nothing(migrated_db: dict[str, Engine]) -> None:
    kits = parse_kits("brand,item_sku,part_sku,reason_he\nTKU,MAIN,NOPE,x\n")
    with Session(migrated_db["owner"]) as s, pytest.raises(CatalogFormatError) as e:
        load(s, parse("brand,sku,family\nTKU,MAIN,relay\n"), kits)
    assert e.value.errors == ["TKU NOPE is not in the catalog"]
