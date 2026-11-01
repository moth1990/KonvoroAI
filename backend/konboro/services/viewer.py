"""The drawing viewer's pyramid, served from stage 2's pack (12 §6, S10 decision "the viewer's pyramid").

Stage 2 writes each page's Deep Zoom image as `dz/page.dzi`, one `dz/tiles.bin` and a `dz/index.json` that maps
`"{level}/{col}_{row}"` to `[offset, length]` in the pack (`pipeline/extraction/deepzoom.py`). A tile request reads
the index once (then from memory) and answers with a ranged read of the pack.

Runs inside `tenant_session`: the page is looked up under RLS, and every key is built from the caller's tenant, so
another tenant's page is "not found" and storage refuses another tenant's key anyway.
"""

import json
import threading
from collections import OrderedDict
from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from konboro.db import models as m

from .storage import Storage, drawing_key

INDEX_CACHE_SIZE = 256  # pages; an A0 sheet's index is about 15 kB


@dataclass(frozen=True)
class Pyramid:
    """Where one page's pyramid lives."""

    tenant_id: str
    page_id: str
    prefix: str  # `tenants/{t}/drawings/{d}/pages/{p}/dz/`

    def key(self, name: str) -> str:
        return self.prefix + name


def pyramid(session: Session, tenant_id: str, page_id: str) -> Pyramid | None:
    """The page's pyramid, or None for a page that is not the tenant's or that stage 2 has not rendered."""
    row = session.execute(
        select(m.Page.drawing_id, m.Page.tiles_prefix).where(m.Page.tenant_id == tenant_id, m.Page.id == page_id)
    ).first()
    if row is None or row.tiles_prefix is None:
        return None
    return Pyramid(tenant_id, page_id, drawing_key(tenant_id, row.drawing_id, "pages", page_id, "dz") + "/")


class TileIndexes:
    """`index.json` per page, kept in memory: a page's pyramid never changes once stage 2 wrote it (a rerun of
    stage 2 renders the same page the same way, and the pack's key includes the page id)."""

    def __init__(self, size: int = INDEX_CACHE_SIZE) -> None:
        self._size = size
        self._items: OrderedDict[str, dict[str, list[int]]] = OrderedDict()
        self._lock = threading.Lock()

    def get(self, storage: Storage, p: Pyramid) -> dict[str, list[int]]:
        key = p.key("index.json")
        with self._lock:
            if key in self._items:
                self._items.move_to_end(key)
                return self._items[key]
        index: dict[str, list[int]] = json.loads(storage.get(p.tenant_id, key))
        with self._lock:
            self._items[key] = index
            while len(self._items) > self._size:
                self._items.popitem(last=False)
        return index


def tile(storage: Storage, indexes: TileIndexes, p: Pyramid, level: int, col: int, row: int) -> bytes | None:
    """One tile's PNG, or None when the pyramid has no such tile."""
    span = indexes.get(storage, p).get(f"{level}/{col}_{row}")
    if span is None:
        return None
    offset, length = span
    return storage.get_range(p.tenant_id, p.key("tiles.bin"), offset, length)
