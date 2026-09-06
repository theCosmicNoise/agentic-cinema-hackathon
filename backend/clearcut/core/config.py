"""Runtime configuration, loaded from .env."""

from __future__ import annotations

import logging
import os
from functools import lru_cache
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel

REPO_ROOT = Path(__file__).resolve().parents[3]
load_dotenv(REPO_ROOT / ".env")


class Settings(BaseModel):
    parallel_api_key: str = ""
    google_api_key: str = ""
    google_cloud_project: str = ""
    google_cloud_location: str = "us-central1"
    use_vertex: bool = False
    # Verified reachable on this key. Pro tiers are quota-gated on the free
    # tier (429), and several flash aliases intermittently 503 — so every call
    # walks a fallback chain rather than trusting one model id.
    gemini_model: str = "gemini-2.5-flash"
    gemini_fast_model: str = "gemini-2.5-flash-lite"
    # Curated by probing this key directly. Excluded: gemini-2.5-flash (404,
    # closed to new keys) and the *-lite / 3.6 variants (400 — they reject
    # thinking_config). Order is best-quality first.
    # Vertex and AI Studio expose different model catalogues, so the chain is
    # selected per backend. Vertex entries verified by probing this project in
    # us-central1; the 3.x ids that AI Studio serves are 404 there.
    gemini_fallbacks: list[str] = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
    ]
    gemini_fallbacks_aistudio: list[str] = [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-3.8-flash",
        "gemini-flash-latest",
    ]

    @property
    def model_chain(self) -> list[str]:
        return self.gemini_fallbacks if self.use_vertex else self.gemini_fallbacks_aistudio
    data_dir: Path = REPO_ROOT / "data"
    # Set to a Cloud Storage bucket and the ledger and sessions live there
    # instead of on the instance, which is what makes them survive a cold start.
    bucket: str = ""
    log_level: str = "INFO"

    def require_parallel(self) -> str:
        if not self.parallel_api_key:
            raise RuntimeError("PARALLEL_API_KEY missing — see .env.example")
        return self.parallel_api_key

    def require_google(self) -> str:
        if self.use_vertex:
            if not self.google_cloud_project:
                raise RuntimeError("GOOGLE_CLOUD_PROJECT missing — see .env.example")
            return self.google_cloud_project
        if not self.google_api_key:
            raise RuntimeError("GOOGLE_API_KEY missing — see .env.example")
        return self.google_api_key


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    s = Settings(
        parallel_api_key=os.environ.get("PARALLEL_API_KEY", ""),
        google_api_key=os.environ.get("GOOGLE_API_KEY", ""),
        google_cloud_project=os.environ.get("GOOGLE_CLOUD_PROJECT", ""),
        google_cloud_location=os.environ.get("GOOGLE_CLOUD_LOCATION", "us-central1"),
        use_vertex=os.environ.get("GOOGLE_GENAI_USE_VERTEXAI", "FALSE").upper() == "TRUE",
        data_dir=Path(os.environ.get("CLEARCUT_DATA_DIR", str(REPO_ROOT / "data"))),
        bucket=os.environ.get("CLEARCUT_BUCKET", ""),
        log_level=os.environ.get("CLEARCUT_LOG_LEVEL", "INFO"),
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return s
