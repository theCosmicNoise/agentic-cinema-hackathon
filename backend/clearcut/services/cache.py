"""
Content-addressed disk cache for model and research calls.

Three reasons this exists, in order of importance:

1. Reproducibility. A clearance report is a legal artifact. Re-running the same
   draft should produce the same findings from the same sources, not a new
   sample from a model.
2. Demo integrity. A live judged run cannot depend on a third-party endpoint
   being healthy in that exact minute.
3. Cost. Iterating on downstream agents should not re-pay for upstream
   extraction and research.

Keys are SHA-256 over the full request payload, so any change to a prompt,
objective or model invalidates its entry automatically.
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


class DiskCache:
    def __init__(self, root: Path, namespace: str, enabled: bool = True):
        self.dir = Path(root) / "cache" / namespace
        self.enabled = enabled
        if enabled:
            self.dir.mkdir(parents=True, exist_ok=True)
        self._lock = threading.Lock()
        self.hits = 0
        self.misses = 0

    @staticmethod
    def key(payload: dict[str, Any]) -> str:
        blob = json.dumps(payload, sort_keys=True, default=str)
        return hashlib.sha256(blob.encode()).hexdigest()[:32]

    def get(self, key: str) -> Any | None:
        if not self.enabled:
            return None
        path = self.dir / f"{key}.json"
        if not path.exists():
            with self._lock:
                self.misses += 1
            return None
        try:
            value = json.loads(path.read_text())
        except (json.JSONDecodeError, OSError):
            return None
        with self._lock:
            self.hits += 1
        return value

    def put(self, key: str, value: Any) -> None:
        if not self.enabled:
            return
        try:
            # Write-then-rename so a crash mid-write cannot leave a torn entry.
            tmp = self.dir / f"{key}.tmp"
            tmp.write_text(json.dumps(value, default=str))
            tmp.rename(self.dir / f"{key}.json")
        except OSError as exc:
            logger.debug("cache write failed for %s: %s", key, exc)

    @property
    def stats(self) -> dict[str, int]:
        return {"hits": self.hits, "misses": self.misses}
