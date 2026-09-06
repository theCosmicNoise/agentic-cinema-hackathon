"""
Where durable state lives.

Cloud Run gives each instance its own /tmp and throws it away when the instance
goes. That is fine for a cache and wrong for a clearance ledger, which is the
production's record of what has already been cleared and is the one thing here
that must outlive a cold start.

So the ledger and the session store read and write through this rather than
touching the filesystem directly. Point CLEARCUT_BUCKET at a bucket and state
goes to Cloud Storage; leave it unset and it stays on local disk, which is what
you want when developing.

Deliberately not covered: the model and research cache. Losing it costs a repeat
call, not a fact, and putting every cache lookup on a network round trip would
make the common case slower to protect something that does not matter.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

logger = logging.getLogger(__name__)


class BlobStore(Protocol):
    """Keys look like 'ledger/the_long_odds.json'. Values are text."""

    def read(self, key: str) -> str | None: ...
    def write(self, key: str, data: str) -> None: ...
    def delete(self, key: str) -> bool: ...
    def list(self, prefix: str) -> list[str]: ...
    def modified(self, key: str) -> datetime | None: ...


class LocalBlobs:
    """Files under a root directory. The development default."""

    def __init__(self, root: Path):
        self.root = Path(root)

    def _p(self, key: str) -> Path:
        return self.root / key

    def read(self, key: str) -> str | None:
        p = self._p(key)
        try:
            return p.read_text() if p.exists() else None
        except OSError as exc:
            logger.warning("could not read %s: %s", key, exc)
            return None

    def write(self, key: str, data: str) -> None:
        p = self._p(key)
        p.parent.mkdir(parents=True, exist_ok=True)
        # Write then rename, so a crash mid-write cannot leave a torn ledger.
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(data)
        tmp.rename(p)

    def delete(self, key: str) -> bool:
        p = self._p(key)
        if not p.exists():
            return False
        p.unlink()
        return True

    def list(self, prefix: str) -> list[str]:
        base = self.root / prefix
        if not base.exists():
            return []
        return sorted(f"{prefix}/{p.name}" for p in base.glob("*.json"))

    def modified(self, key: str) -> datetime | None:
        p = self._p(key)
        if not p.exists():
            return None
        return datetime.fromtimestamp(p.stat().st_mtime, tz=timezone.utc)


class GcsBlobs:
    """Objects in a Cloud Storage bucket. Survives cold starts and instances."""

    def __init__(self, bucket: str, prefix: str = "clearcut"):
        from google.cloud import storage  # imported here so local runs need no GCS

        self._client = storage.Client()
        self._bucket = self._client.bucket(bucket)
        self._prefix = prefix.strip("/")

    def _name(self, key: str) -> str:
        return f"{self._prefix}/{key}" if self._prefix else key

    def read(self, key: str) -> str | None:
        blob = self._bucket.blob(self._name(key))
        try:
            return blob.download_as_text() if blob.exists() else None
        except Exception as exc:  # noqa: BLE001
            logger.warning("could not read gs://%s: %s", self._name(key), exc)
            return None

    def write(self, key: str, data: str) -> None:
        # Object writes are atomic, so no temp-and-rename dance is needed.
        self._bucket.blob(self._name(key)).upload_from_string(
            data, content_type="application/json"
        )

    def delete(self, key: str) -> bool:
        blob = self._bucket.blob(self._name(key))
        if not blob.exists():
            return False
        blob.delete()
        return True

    def list(self, prefix: str) -> list[str]:
        full = self._name(prefix).rstrip("/") + "/"
        out = []
        for b in self._client.list_blobs(self._bucket, prefix=full):
            if b.name.endswith(".json"):
                out.append(b.name[len(self._prefix) + 1:] if self._prefix else b.name)
        return sorted(out)

    def modified(self, key: str) -> datetime | None:
        blob = self._bucket.blob(self._name(key))
        try:
            if not blob.exists():
                return None
            blob.reload()
            return blob.updated
        except Exception:  # noqa: BLE001
            return None


_store: BlobStore | None = None


def get_blobs() -> BlobStore:
    """The store this deployment uses. GCS when a bucket is configured."""
    global _store
    if _store is not None:
        return _store

    from clearcut.core.config import get_settings

    s = get_settings()
    if s.bucket:
        try:
            _store = GcsBlobs(s.bucket)
            logger.info("state in gs://%s", s.bucket)
            return _store
        except Exception as exc:  # noqa: BLE001
            # A misconfigured bucket should degrade to working-but-ephemeral
            # rather than take the whole service down on startup.
            logger.error("bucket %s unusable (%s); falling back to disk", s.bucket, exc)

    _store = LocalBlobs(s.data_dir)
    return _store


def reset_blobs() -> None:
    """Drop the cached store. For tests."""
    global _store
    _store = None
