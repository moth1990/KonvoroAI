"""Files in S3 (12 §3): one prefix per tenant, server-side encryption on every object.

Every key is built here from a tenant id, and every read checks the key is under that tenant's prefix, so code
can't reach another tenant's files by passing the wrong key (docs/db-schema.md §2).
"""

from typing import Any

from konboro.db.ids import is_id
from konboro.settings import Settings

from . import aws


class TenantKeyError(ValueError):
    """A key outside the tenant's prefix, or an invalid tenant id."""


def tenant_prefix(tenant_id: str) -> str:
    if not is_id(tenant_id, "tnt"):
        raise TenantKeyError(f"not a tenant id: {tenant_id!r}")
    return f"tenants/{tenant_id}/"


def drawing_key(tenant_id: str, drawing_id: str, *parts: str) -> str:
    """`tenants/{tenant}/drawings/{drawing}/{parts…}`."""
    if not is_id(drawing_id, "drw"):
        raise TenantKeyError(f"not a drawing id: {drawing_id!r}")
    if any(not p or "/" in p or p in (".", "..") for p in parts):
        raise TenantKeyError(f"bad key part in {parts!r}")
    return tenant_prefix(tenant_id) + "/".join(("drawings", drawing_id, *parts))


class Storage:
    def __init__(self, settings: Settings, s3: Any | None = None) -> None:
        self.bucket = settings.s3_bucket
        self.sse = settings.s3_sse
        self.s3 = s3 or aws.client("s3", settings)
        self._local = settings.env in ("local", "test") and settings.s3_endpoint is not None

    def reset_local_bucket(self) -> None:
        """Tests, E2E and the eval each start on an empty bucket of their own: S3Mock slows down with every object
        a bucket holds (a put took 270 ms at 27,000 objects, 5 ms on an empty bucket), and stage 2 writes dozens
        per page (S10). Only against the local S3 stand-in, never AWS."""
        if not self._local:
            raise RuntimeError("reset_local_bucket is for the local S3 stand-in only")
        try:
            self.s3.head_bucket(Bucket=self.bucket)
        except self.s3.exceptions.ClientError:
            self.s3.create_bucket(Bucket=self.bucket)
            return
        for page in self.s3.get_paginator("list_objects_v2").paginate(Bucket=self.bucket):
            keys = [{"Key": o["Key"]} for o in page.get("Contents", [])]
            if keys:
                self.s3.delete_objects(Bucket=self.bucket, Delete={"Objects": keys, "Quiet": True})

    def _check(self, tenant_id: str, key: str) -> None:
        if not key.startswith(tenant_prefix(tenant_id)) or ".." in key.split("/"):
            raise TenantKeyError(f"{key!r} is not under tenant {tenant_id}")

    def put(self, tenant_id: str, key: str, body: bytes, content_type: str = "application/octet-stream") -> None:
        self._check(tenant_id, key)
        self.s3.put_object(
            Bucket=self.bucket, Key=key, Body=body, ContentType=content_type, ServerSideEncryption=self.sse
        )

    def get(self, tenant_id: str, key: str) -> bytes:
        self._check(tenant_id, key)
        body: bytes = self.s3.get_object(Bucket=self.bucket, Key=key)["Body"].read()
        return body

    def presigned_get(self, tenant_id: str, key: str, expires_s: int = 300) -> str:
        """A short-lived URL the browser can load directly (thumbnails)."""
        self._check(tenant_id, key)
        url: str = self.s3.generate_presigned_url(
            "get_object", Params={"Bucket": self.bucket, "Key": key}, ExpiresIn=expires_s
        )
        return url
