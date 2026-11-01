"""The drawing viewer's pyramid over HTTP (09 §6.5, 12 §6; S11): `page.dzi` and one tile, a ranged read of stage 2's
pack, tenant-scoped and behind `review_screen`. Measured on the NURSERY fixture's pages (S11 decision 2)."""

import io
import json
from collections.abc import Iterator

import pytest
from PIL import Image
from sqlalchemy import Engine, select
from sqlalchemy.orm import Session

from konboro.db import models as m
from konboro.db.seed import seed_global
from konboro.db.session import tenant_session
from konboro.devtools.fixtures.nursery import MARKER, seed_nursery, seed_nursery_pages
from konboro.services.storage import Storage

from .api import Api, set_tenant_flag

FLAG = "review_screen"


@pytest.fixture(scope="module")
def pages(api: Api, migrated_db: dict[str, Engine], storage: Storage) -> Iterator[list[m.Page]]:
    """The fixture's 9 pages in tenant A, with their images; the flag on in both tenants."""
    with Session(migrated_db["owner"]) as s, s.begin():
        seed_global(s)
    with tenant_session(api.a.tenant_id, api.engine) as s:
        seed_nursery(s, api.a.tenant_id)
        assert seed_nursery_pages(s, storage, api.a.tenant_id) == 9
    for t in (api.a, api.b):
        set_tenant_flag(api.engine, t.tenant_id, FLAG, True)
    yield _pages(api)


def _pages(api: Api) -> list[m.Page]:
    with tenant_session(api.a.tenant_id, api.engine) as s:
        drawing = s.scalar(select(m.Drawing.id).where(m.Drawing.trace_id == MARKER))
        rows = list(s.scalars(select(m.Page).where(m.Page.drawing_id == drawing).order_by(m.Page.page_no)))
        s.expunge_all()
    return rows


def _url(page: m.Page, tail: str = "page.dzi") -> str:
    return f"/pages/{page.id}/dz/{tail}"


def test_the_fixture_pages_have_their_images_once(api: Api, pages: list[m.Page], storage: Storage) -> None:
    assert len(pages) == 9
    for p in pages:
        assert p.render_key is not None and p.render_key.endswith(f"/pages/{p.id}/render.png")
        assert p.tiles_prefix is not None and p.tiles_prefix.endswith(f"/pages/{p.id}/tiles/")
        assert storage.exists(api.a.tenant_id, p.render_key.replace("render.png", "thumb.png"))
    with tenant_session(api.a.tenant_id, api.engine) as s:
        assert seed_nursery_pages(s, storage, api.a.tenant_id) == 0  # everything is there already
    # a bucket emptied under the database (a test run) gets the images again
    index = pages[0].render_key.replace("render.png", "dz/index.json")  # type: ignore[union-attr]
    storage.s3.delete_object(Bucket=storage.bucket, Key=index)
    with tenant_session(api.a.tenant_id, api.engine) as s:
        assert seed_nursery_pages(s, storage, api.a.tenant_id) == 1
    assert storage.exists(api.a.tenant_id, index)


def test_the_descriptor(api: Api, pages: list[m.Page]) -> None:
    r = api.client.get(_url(pages[4]), headers=api.as_(api.a))
    assert r.status_code == 200, r.text
    assert r.headers["content-type"] == "application/xml"
    assert "private" in r.headers["cache-control"]
    assert 'TileSize="510"' in r.text and 'Overlap="1"' in r.text
    assert '<Size Width="1400" Height="989"/>' in r.text


def test_a_tile_is_the_packed_bytes(api: Api, pages: list[m.Page], storage: Storage) -> None:
    page = pages[4]
    prefix = page.render_key.replace("render.png", "dz/")  # type: ignore[union-attr]
    index = json.loads(storage.get(api.a.tenant_id, prefix + "index.json"))
    packed = storage.get(api.a.tenant_id, prefix + "tiles.bin")
    top = max(int(k.split("/")[0]) for k in index)
    for key in (f"{top}/0_0", f"{top}/2_1", "0/0_0"):
        level, cr = key.split("/")
        r = api.client.get(_url(page, f"page_files/{level}/{cr}.png"), headers=api.as_(api.a))
        assert r.status_code == 200, (key, r.text)
        assert r.headers["content-type"] == "image/png"
        offset, length = index[key]
        assert r.content == packed[offset : offset + length]
    r = api.client.get(_url(page, f"page_files/{top}/0_0.png"), headers=api.as_(api.a))
    first = Image.open(io.BytesIO(r.content))
    assert first.size == (511, 511)  # 510 and the overlap on the far side


def test_a_tile_outside_the_pyramid_is_not_found(api: Api, pages: list[m.Page]) -> None:
    r = api.client.get(_url(pages[4], "page_files/11/99_0.png"), headers=api.as_(api.a))
    assert r.status_code == 404
    assert api.client.get(_url(pages[4], "page_files/x/0_0.png"), headers=api.as_(api.a)).status_code == 422
    assert api.client.get("/pages/not-a-page/dz/page.dzi", headers=api.as_(api.a)).status_code == 422


def test_another_tenants_page_is_not_found(api: Api, pages: list[m.Page]) -> None:
    for tail in ("page.dzi", "page_files/0/0_0.png"):
        r = api.client.get(_url(pages[4], tail), headers=api.as_(api.b))
        assert r.status_code == 404
        assert r.json()["error"]["code"] == "not_found"


def test_a_page_stage_2_has_not_rendered_is_not_found(api: Api, pages: list[m.Page]) -> None:
    with tenant_session(api.a.tenant_id, api.engine) as s:
        page = s.get(m.Page, pages[0].id)
        assert page is not None
        prefix, page.tiles_prefix = page.tiles_prefix, None
    try:
        assert api.client.get(_url(pages[0]), headers=api.as_(api.a)).status_code == 404
    finally:
        with tenant_session(api.a.tenant_id, api.engine) as s:
            page = s.get(m.Page, pages[0].id)
            assert page is not None
            page.tiles_prefix = prefix


def test_with_the_flag_off_the_routes_do_not_exist(api: Api, pages: list[m.Page]) -> None:
    set_tenant_flag(api.engine, api.a.tenant_id, FLAG, False)
    try:
        assert api.client.get(_url(pages[4]), headers=api.as_(api.a)).status_code == 404
        assert api.client.get(_url(pages[4], "page_files/0/0_0.png"), headers=api.as_(api.a)).status_code == 404
    finally:
        set_tenant_flag(api.engine, api.a.tenant_id, FLAG, True)


def test_without_a_token(api: Api, pages: list[m.Page]) -> None:
    assert api.client.get(_url(pages[4])).status_code == 401
