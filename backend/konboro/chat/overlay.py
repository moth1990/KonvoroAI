"""Storage for a what-if (08 §7.2): writes stay in memory and are read back, so stage 6's rerun on the copy never
reaches S3; the database side is a SAVEPOINT that is rolled back."""

from typing import Any

from konboro.services.storage import Storage


class OverlayStorage:
    def __init__(self, base: Storage) -> None:
        self.base = base
        self.written: dict[tuple[str, str], bytes | None] = {}

    def put(self, tenant_id: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        self.base._check(tenant_id, key)
        self.written[(tenant_id, key)] = body

    def get(self, tenant_id: str, key: str) -> bytes:
        if (tenant_id, key) in self.written:
            body = self.written[(tenant_id, key)]
            if body is None:
                raise KeyError(key)
            return body
        return self.base.get(tenant_id, key)

    def delete(self, tenant_id: str, key: str) -> None:
        self.base._check(tenant_id, key)
        self.written[(tenant_id, key)] = None

    def exists(self, tenant_id: str, key: str) -> bool:
        if (tenant_id, key) in self.written:
            return self.written[(tenant_id, key)] is not None
        return self.base.exists(tenant_id, key)

    def __getattr__(self, name: str) -> Any:
        return getattr(self.base, name)
