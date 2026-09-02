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
    gemini_model: str = "gemini-3.5-flash"
    gemini_fast_model: str = "gemini-3.5-flash-lite"
    gemini_fallbacks: list[str] = [
        "gemini-3.5-flash",
        "gemini-3-flash-preview",
        "gemini-2.5-flash",
        "gemini-3.5-flash-lite",
    ]
    data_dir: Path = REPO_ROOT / "data"
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
        log_level=os.environ.get("CLEARCUT_LOG_LEVEL", "INFO"),
    )
    s.data_dir.mkdir(parents=True, exist_ok=True)
    logging.basicConfig(
        level=getattr(logging, s.log_level.upper(), logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)s | %(message)s",
        datefmt="%H:%M:%S",
    )
    return s
