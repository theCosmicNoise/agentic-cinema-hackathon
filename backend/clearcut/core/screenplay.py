"""
Screenplay ingestion.

Clearance reports are page-cited — a producer needs to turn to page 14 and see
the line. So the first job is not extraction, it is establishing a coordinate
system: scenes, and the page each line falls on.

Page estimation follows the industry constant: a correctly formatted page is
55 lines of 12pt Courier. That is also why one script page is roughly one
minute of screen time.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from clearcut.core.models import ScriptMeta

LINES_PER_PAGE = 55

_SLUG = re.compile(
    r"^\s*((?:INT\.?/EXT\.?|EXT\.?/INT\.?|INT\.?|EXT\.?|I/E\.?)\s+.+)$",
    re.IGNORECASE,
)
_SCENE_NUM = re.compile(r"^\s*(\d+[A-Z]?)\s+((?:INT|EXT|I/E).+?)(?:\s+\1)?\s*$", re.I)
_DRAFT = re.compile(
    r"\b(WHITE|BLUE|PINK|YELLOW|GREEN|GOLDENROD|BUFF|SALMON|CHERRY|TAN)\b", re.I
)
_DATE = re.compile(r"\b((?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\s+\d{1,2},?\s+\d{4})\b")


@dataclass
class Scene:
    index: int
    scene_number: str | None
    heading: str
    start_page: int
    end_page: int
    text: str

    @property
    def label(self) -> str:
        return f"Scene {self.scene_number or self.index} — {self.heading}"


@dataclass
class ParsedScreenplay:
    meta: ScriptMeta
    scenes: list[Scene] = field(default_factory=list)
    raw: str = ""

    @property
    def total_pages(self) -> int:
        return self.meta.page_count


# Inserted between PDF pages so real pagination survives text extraction.
PAGE_BREAK = "\x0c"


def load_screenplay(path: str | Path) -> str:
    """Read a screenplay from .txt/.fountain or a Final Draft-style PDF.

    For PDFs the real page boundaries are preserved as form feeds. A clearance
    report is page-cited and a producer turns to that page, so an estimated
    page number is not good enough when the true one is available.
    """
    p = Path(path)
    if p.suffix.lower() == ".pdf":
        from pypdf import PdfReader

        reader = PdfReader(str(p))
        return PAGE_BREAK.join((pg.extract_text() or "") for pg in reader.pages)
    return p.read_text(encoding="utf-8", errors="replace")


def parse_screenplay(text: str, *, title: str | None = None) -> ParsedScreenplay:
    """Split into scenes and assign page numbers to each."""
    lines = text.splitlines()
    meta = _extract_meta(lines, title=title)

    # Prefer true pagination when the source carried it (PDF form feeds);
    # fall back to the 55-line convention for plain text and Fountain.
    page_of_line = _true_pages(lines)
    if page_of_line:
        meta.page_count = max(page_of_line.values())
        lines = [ln.replace(PAGE_BREAK, "") for ln in lines]
    else:
        meta.page_count = max(1, (len(lines) + LINES_PER_PAGE - 1) // LINES_PER_PAGE)

    # Locate every slug line — these are the scene boundaries.
    boundaries: list[tuple[int, str | None, str]] = []
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped:
            continue
        numbered = _SCENE_NUM.match(stripped)
        if numbered:
            boundaries.append((i, numbered.group(1), numbered.group(2).strip()))
            continue
        slug = _SLUG.match(stripped)
        if slug:
            boundaries.append((i, None, slug.group(1).strip()))

    def page_at(i: int) -> int:
        return page_of_line.get(i, _page_of(i)) if page_of_line else _page_of(i)

    scenes: list[Scene] = []
    if not boundaries:
        # No slug lines (treatment, sides, partial pages) — treat as one unit.
        scenes.append(
            Scene(1, None, "(no scene heading)", 1, meta.page_count, text)
        )
    else:
        for n, (start, num, heading) in enumerate(boundaries):
            end = boundaries[n + 1][0] if n + 1 < len(boundaries) else len(lines)
            scenes.append(
                Scene(
                    index=n + 1,
                    scene_number=num,
                    heading=heading,
                    start_page=page_at(start),
                    end_page=page_at(max(start, end - 1)),
                    text="\n".join(lines[start:end]),
                )
            )

    return ParsedScreenplay(meta=meta, scenes=scenes, raw=text)


def _page_of(line_index: int) -> int:
    return line_index // LINES_PER_PAGE + 1


def _true_pages(lines: list[str]) -> dict[int, int]:
    """Map line index -> real page number, when the source carried page breaks."""
    if not any(PAGE_BREAK in ln for ln in lines):
        return {}
    mapping: dict[int, int] = {}
    page = 1
    for i, ln in enumerate(lines):
        mapping[i] = page
        page += ln.count(PAGE_BREAK)
    return mapping


def _extract_meta(lines: list[str], *, title: str | None) -> ScriptMeta:
    head = [ln.strip() for ln in lines[:40] if ln.strip()]
    meta = ScriptMeta(title=title or (head[0] if head else "Untitled"))

    for i, ln in enumerate(head[:12]):
        if ln.lower().startswith(("written by", "by ")) and i + 1 < len(head):
            meta.author = head[i + 1]
            break

    blob = "\n".join(head)
    if (m := _DRAFT.search(blob)):
        meta.draft_label = m.group(1).title()
    if (m := _DATE.search(blob)):
        meta.draft_date = m.group(1)
    return meta
