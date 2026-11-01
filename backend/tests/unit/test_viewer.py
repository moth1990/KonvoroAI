"""The viewer's tile lookup (services/viewer.py, S11): the pack's index is read once per page, kept in a bounded
cache, and a tile is a ranged read of the pack."""

import json

from PIL import Image

from konboro.pipeline.extraction import deepzoom
from konboro.services import viewer

TENANT = "tnt_01JD0000000000000000000000"


class FakeStorage:
    def __init__(self, objects: dict[str, bytes]) -> None:
        self.objects = objects
        self.gets: list[str] = []

    def get(self, tenant_id: str, key: str) -> bytes:
        self.gets.append(key)
        return self.objects[key]

    def get_range(self, tenant_id: str, key: str, offset: int, length: int) -> bytes:
        return self.objects[key][offset : offset + length]


def _pyramid(page: str) -> viewer.Pyramid:
    return viewer.Pyramid(TENANT, page, f"tenants/{TENANT}/drawings/d/pages/{page}/dz/")


def _storage(*pages: str) -> FakeStorage:
    packed, index = deepzoom.pack(Image.new("RGB", (700, 400), "white"), 510, 1)
    objects: dict[str, bytes] = {}
    for page in pages:
        p = _pyramid(page)
        objects[p.key("tiles.bin")], objects[p.key("index.json")] = packed, index
    return FakeStorage(objects)


def test_a_tile_is_its_range_of_the_pack() -> None:
    storage, p = _storage("pg_1"), _pyramid("pg_1")
    index = json.loads(storage.objects[p.key("index.json")])
    offset, length = index["10/1_0"]
    body = viewer.tile(storage, viewer.TileIndexes(), p, 10, 1, 0)  # type: ignore[arg-type]
    assert body == storage.objects[p.key("tiles.bin")][offset : offset + length]
    assert body is not None and body.startswith(b"\x89PNG")


def test_a_tile_outside_the_pyramid_is_none() -> None:
    storage, p = _storage("pg_1"), _pyramid("pg_1")
    assert viewer.tile(storage, viewer.TileIndexes(), p, 10, 5, 0) is None  # type: ignore[arg-type]
    assert viewer.tile(storage, viewer.TileIndexes(), p, 31, 0, 0) is None  # type: ignore[arg-type]


def test_the_index_is_read_once_per_page_and_the_cache_is_bounded() -> None:
    storage = _storage("pg_1", "pg_2", "pg_3")
    indexes = viewer.TileIndexes(size=2)
    for _ in range(3):
        viewer.tile(storage, indexes, _pyramid("pg_1"), 0, 0, 0)  # type: ignore[arg-type]
    assert storage.gets == [_pyramid("pg_1").key("index.json")]
    viewer.tile(storage, indexes, _pyramid("pg_2"), 0, 0, 0)  # type: ignore[arg-type]
    viewer.tile(storage, indexes, _pyramid("pg_1"), 0, 0, 0)  # type: ignore[arg-type]  # pg_1 is the newest now
    viewer.tile(storage, indexes, _pyramid("pg_3"), 0, 0, 0)  # type: ignore[arg-type]  # pg_2 leaves
    viewer.tile(storage, indexes, _pyramid("pg_1"), 0, 0, 0)  # type: ignore[arg-type]
    viewer.tile(storage, indexes, _pyramid("pg_2"), 0, 0, 0)  # type: ignore[arg-type]
    assert [k.split("/")[5] for k in storage.gets] == ["pg_1", "pg_2", "pg_3", "pg_2"]
