"""
Render a fixture screenplay as a properly formatted PDF.

Industry format: 12pt Courier, 1.5" left margin, 1" elsewhere, page numbers top
right. Revision drafts are printed on coloured stock so a crew member can tell
at a glance which pages supersede which, so the draft colour named in the title
page tints the paper here too.

    python3 tools/render_screenplay.py assets/screenplays/the_long_odds_v1.txt
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

from reportlab.lib.colors import Color, black
from reportlab.lib.pagesizes import LETTER
from reportlab.pdfgen import canvas

INCH = 72.0
PAGE_W, PAGE_H = LETTER

# Distances from the left edge of the paper, as a script supervisor would set them.
LEFT_ACTION = 1.5 * INCH
LEFT_DIALOGUE = 2.5 * INCH
LEFT_PAREN = 3.1 * INCH
LEFT_CHARACTER = 3.7 * INCH
RIGHT_EDGE = PAGE_W - 1.0 * INCH
TOP = PAGE_H - 1.0 * INCH
BOTTOM = 1.0 * INCH
LINE = 12.0                      # 12pt Courier, single spaced
DIALOGUE_CHARS = 35              # dialogue wraps narrower than action
ACTION_CHARS = 60

# Revision stock, in the order productions use it.
PAPER = {
    "white": None,
    "blue": Color(0.85, 0.90, 0.97),
    "pink": Color(0.99, 0.89, 0.93),
    "yellow": Color(1.00, 0.98, 0.82),
    "green": Color(0.88, 0.95, 0.88),
    "goldenrod": Color(0.99, 0.94, 0.75),
}

SLUG = re.compile(r"^\s*(INT\.|EXT\.|INT/EXT|I/E|FADE IN:|FADE OUT)", re.I)
TRANSITION = re.compile(r"(CUT TO:|DISSOLVE TO:|FADE OUT\.?|FADE IN:|SMASH CUT:)\s*$", re.I)
CHARACTER = re.compile(r"^\s{20,}([A-Z][A-Z0-9 .'\-]{1,30})(\s*\(CONT'D\))?\s*$")
PAREN = re.compile(r"^\s*\(.*\)\s*$")


def classify(raw: str) -> tuple[str, str]:
    """Work out which screenplay element a line is, and return it trimmed.

    Indentation carries the meaning in a screenplay: character cues sit around
    twenty spaces in, parentheticals around sixteen, and dialogue around ten,
    with action flush at the margin.
    """
    line = raw.rstrip()
    stripped = line.strip()
    if not stripped:
        return "blank", ""
    indent = len(line) - len(line.lstrip())
    if TRANSITION.search(stripped):
        return "transition", stripped
    if SLUG.match(stripped):
        return "slug", stripped
    if indent >= 16 and CHARACTER.match(line):
        return "character", stripped
    if indent >= 8 and PAREN.match(line):
        return "paren", stripped
    if indent >= 8:
        return "dialogue", stripped
    return "action", stripped


def wrap(text: str, width: int) -> list[str]:
    out, cur = [], ""
    for word in text.split():
        if len(cur) + len(word) + 1 > width and cur:
            out.append(cur)
            cur = word
        else:
            cur = f"{cur} {word}".strip()
    if cur:
        out.append(cur)
    return out or [""]


def render(src: Path, dest: Path) -> Path:
    text = src.read_text(encoding="utf-8", errors="replace")
    colour_word = next(
        (c for c in PAPER if re.search(rf"\({c}\)", text, re.I)), "white"
    )
    stock = PAPER[colour_word]

    c = canvas.Canvas(str(dest), pagesize=LETTER)
    c.setTitle(src.stem.replace("_", " ").title())

    lines = text.splitlines()
    # Everything before FADE IN is the title page.
    try:
        split = next(i for i, l in enumerate(lines) if l.strip().upper().startswith("FADE IN"))
    except StopIteration:
        split = 0
    title_lines = [l.strip() for l in lines[:split] if l.strip()]
    body = lines[split:]

    def new_page(number: int | None) -> None:
        if stock is not None:
            c.setFillColor(stock)
            c.rect(0, 0, PAGE_W, PAGE_H, stroke=0, fill=1)
        c.setFillColor(black)
        c.setFont("Courier", 12)
        if number:
            c.drawRightString(RIGHT_EDGE, PAGE_H - 0.6 * INCH, f"{number}.")

    # Title page, centred, as a cover sheet rather than page one.
    new_page(None)
    y = PAGE_H * 0.62
    for i, t in enumerate(title_lines):
        c.setFont("Courier-Bold" if i == 0 else "Courier", 12)
        c.drawCentredString(PAGE_W / 2, y, t.upper() if i == 0 else t)
        y -= LINE * (2 if i == 0 else 1.4)
    c.showPage()

    page = 1
    new_page(page)
    y = TOP

    def feed(n: float = 1.0) -> None:
        nonlocal y, page
        y -= LINE * n
        if y < BOTTOM:
            c.showPage()
            page += 1
            new_page(page)
            y = TOP

    # Gather consecutive action or dialogue lines into one paragraph first.
    blocks: list[tuple[str, str]] = []
    for raw in body:
        kind, content = classify(raw)
        if kind in ("action", "dialogue") and blocks and blocks[-1][0] == kind:
            blocks[-1] = (kind, f"{blocks[-1][1]} {content}".strip())
        else:
            blocks.append((kind, content))

    for kind, content in blocks:
        if kind == "blank":
            feed(1)
            continue
        if kind == "slug":
            feed(1)
            c.setFont("Courier-Bold", 12)
            c.drawString(LEFT_ACTION, y, content.upper())
            feed(1)
        elif kind == "transition":
            c.setFont("Courier", 12)
            c.drawRightString(RIGHT_EDGE, y, content.upper())
            feed(1)
        elif kind == "character":
            c.setFont("Courier", 12)
            c.drawString(LEFT_CHARACTER, y, content.upper())
            feed(1)
        elif kind == "paren":
            c.setFont("Courier", 12)
            c.drawString(LEFT_PAREN, y, content)
            feed(1)
        elif kind == "dialogue":
            c.setFont("Courier", 12)
            for w in wrap(content, DIALOGUE_CHARS):
                c.drawString(LEFT_DIALOGUE, y, w)
                feed(1)
        else:
            c.setFont("Courier", 12)
            for w in wrap(content, ACTION_CHARS):
                c.drawString(LEFT_ACTION, y, w)
                feed(1)

    c.save()
    return dest


if __name__ == "__main__":
    for arg in sys.argv[1:]:
        src = Path(arg)
        out = Path("assets/screenplays/pdf") / f"{src.stem}.pdf"
        out.parent.mkdir(parents=True, exist_ok=True)
        render(src, out)
        print(f"  {out}  ({out.stat().st_size // 1024} KB)")
