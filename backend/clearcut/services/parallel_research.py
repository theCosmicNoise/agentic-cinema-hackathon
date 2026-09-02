"""
Parallel Web Systems integration — the evidence engine behind every verdict.

This module is the reason CLEARCUT is a legal instrument and not an LLM
opinion. A model cannot know from weights whether "Zenith Motors" is a live
registered mark today; it has to look. Every ruling in the delivered report
traces back to citations produced here.

Partner-track requirement: Parallel's Search API is called at runtime, on
every clearable item, via the official `parallel-web` SDK.
"""

from __future__ import annotations

import logging
import os
import threading
from typing import Literal

from parallel import Parallel

from clearcut.core.config import get_settings
from clearcut.core.models import Citation, ResearchEvidence
from clearcut.services.cache import DiskCache

logger = logging.getLogger(__name__)

SearchMode = Literal["turbo", "fast", "basic", "advanced"]


class ParallelResearchService:
    """Thin, instrumented wrapper over the Parallel Search and Task APIs."""

    def __init__(self, api_key: str | None = None, default_mode: SearchMode = "fast"):
        key = api_key or os.environ.get("PARALLEL_API_KEY")
        if not key:
            raise RuntimeError(
                "PARALLEL_API_KEY is not set. Copy .env.example to .env and fill it in."
            )
        self._client = Parallel(api_key=key)
        self._default_mode: SearchMode = default_mode
        self._cache = DiskCache(get_settings().data_dir, "parallel")
        self._lock = threading.Lock()
        self.search_calls = 0
        self.task_calls = 0

    # ------------------------------------------------------------------ #
    # Search API — the per-item workhorse
    # ------------------------------------------------------------------ #
    def search(
        self,
        *,
        item_id: str,
        objective: str,
        queries: list[str],
        mode: SearchMode | None = None,
        max_chars_total: int = 4000,
        max_citations: int = 6,
    ) -> ResearchEvidence:
        """Run one clearance lookup and normalise it into cited evidence."""
        mode = mode or self._default_mode
        evidence = ResearchEvidence(
            item_id=item_id,
            objective=objective,
            queries=queries,
            processor=f"search:{mode}",
        )

        ck = self._cache.key(
            {"kind": "search", "objective": objective, "queries": queries,
             "mode": mode, "max_chars": max_chars_total}
        )
        if (cached := self._cache.get(ck)) is not None:
            return ResearchEvidence.model_validate(cached)

        try:
            resp = self._client.search(
                objective=objective,
                search_queries=queries,
                mode=mode,
                max_chars_total=max_chars_total,
            )
        except Exception as exc:  # noqa: BLE001 — a failed lookup must not kill the run
            logger.warning("Parallel search failed for %s: %s", item_id, exc)
            evidence.findings = f"RESEARCH_UNAVAILABLE: {type(exc).__name__}: {exc}"
            return evidence

        with self._lock:
            self.search_calls += 1

        for result in (resp.results or [])[:max_citations]:
            excerpts = getattr(result, "excerpts", None) or []
            evidence.citations.append(
                Citation(
                    url=result.url,
                    title=getattr(result, "title", None),
                    excerpt=_clip(" ".join(excerpts), 700) if excerpts else None,
                )
            )

        evidence.findings = _summarise(evidence.citations)
        self._cache.put(ck, evidence.model_dump())
        return evidence

    # ------------------------------------------------------------------ #
    # Task API — escalation for items that Search cannot settle
    # ------------------------------------------------------------------ #
    def deep_research(
        self,
        *,
        item_id: str,
        objective: str,
        processor: str = "core",
        api_timeout: int = 240,
    ) -> ResearchEvidence:
        """
        Multi-hop verification for high-stakes items.

        Reserved for the cases where a wrong call is expensive: a real person
        who may be identifiable, a mark whose live status is ambiguous, a
        depiction that could be read as defamatory.
        """
        evidence = ResearchEvidence(
            item_id=item_id,
            objective=objective,
            processor=f"task:{processor}",
            escalated=True,
        )

        ck = self._cache.key(
            {"kind": "task", "objective": objective, "processor": processor}
        )
        if (cached := self._cache.get(ck)) is not None:
            return ResearchEvidence.model_validate(cached)

        try:
            run = self._client.task_run.create(input=objective, processor=processor)
            result = self._client.task_run.result(run.run_id, api_timeout=api_timeout)
        except Exception as exc:  # noqa: BLE001
            logger.warning("Parallel task run failed for %s: %s", item_id, exc)
            evidence.findings = f"DEEP_RESEARCH_UNAVAILABLE: {type(exc).__name__}: {exc}"
            return evidence

        with self._lock:
            self.task_calls += 1

        output = getattr(result, "output", None)
        content = getattr(output, "content", None)
        evidence.findings = content if isinstance(content, str) else str(content or "")

        for basis in (getattr(output, "basis", None) or []):
            for cit in (getattr(basis, "citations", None) or []):
                url = getattr(cit, "url", None)
                if not url:
                    continue
                evidence.citations.append(
                    Citation(
                        url=url,
                        title=getattr(cit, "title", None),
                        excerpt=_clip(getattr(cit, "excerpt", None) or "", 700) or None,
                    )
                )

        return evidence

    @property
    def cache_stats(self) -> dict[str, int]:
        return self._cache.stats

    @property
    def total_calls(self) -> int:
        return self.search_calls + self.task_calls


def _clip(text: str, limit: int) -> str:
    text = " ".join(text.split())
    return text if len(text) <= limit else text[: limit - 1] + "…"


def _summarise(citations: list[Citation]) -> str:
    if not citations:
        return "NO_EVIDENCE_FOUND: no web sources matched this objective."
    lines = [f"{len(citations)} source(s) retrieved:"]
    for i, c in enumerate(citations, 1):
        lines.append(f"[{i}] {c.title or c.url} — {c.url}")
        if c.excerpt:
            lines.append(f"    {_clip(c.excerpt, 400)}")
    return "\n".join(lines)
