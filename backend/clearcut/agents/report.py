"""
Agent 6 — Report.

Emits the artifact the industry already recognises: a page-cited, annotated
clearance report an E&O carrier's counsel can read top to bottom.

Two decisions shape the layout. Blocking items come first, because the only
question a producer opens this document to answer is "what stops us shooting".
And every ruling carries its sources inline rather than in an appendix, because
a verdict a reader cannot trace is a verdict they will not rely on.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Callable

from reportlab.lib import colors
from reportlab.lib.enums import TA_LEFT
from reportlab.lib.pagesizes import LETTER
from reportlab.lib.styles import ParagraphStyle, getSampleStyleSheet
from reportlab.lib.units import inch
from reportlab.platypus import (
    HRFlowable,
    KeepTogether,
    PageBreak,
    Paragraph,
    SimpleDocTemplate,
    Spacer,
    Table,
    TableStyle,
)

from clearcut.core.models import AgentEvent, ClearanceReport, Verdict

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]

# Verdict presentation. Order is the order a producer needs them in.
_VERDICT_ORDER = [
    Verdict.MUST_CHANGE,
    Verdict.LICENSE_REQUIRED,
    Verdict.LEGAL_REVIEW,
    Verdict.CLEAR_WITH_CAUTION,
    Verdict.CLEAR,
]
_LABEL = {
    Verdict.MUST_CHANGE: "MUST CHANGE",
    Verdict.LICENSE_REQUIRED: "LICENCE REQUIRED",
    Verdict.LEGAL_REVIEW: "REFER TO COUNSEL",
    Verdict.CLEAR_WITH_CAUTION: "CLEAR WITH CAUTION",
    Verdict.CLEAR: "CLEAR",
}
_COLOR = {
    Verdict.MUST_CHANGE: colors.HexColor("#B3261E"),
    Verdict.LICENSE_REQUIRED: colors.HexColor("#B26A00"),
    Verdict.LEGAL_REVIEW: colors.HexColor("#6750A4"),
    Verdict.CLEAR_WITH_CAUTION: colors.HexColor("#7A6000"),
    Verdict.CLEAR: colors.HexColor("#1B6B30"),
}
_BLOCKING = {Verdict.MUST_CHANGE, Verdict.LICENSE_REQUIRED, Verdict.LEGAL_REVIEW}


def _styles() -> dict[str, ParagraphStyle]:
    base = getSampleStyleSheet()
    return {
        "title": ParagraphStyle(
            "t", parent=base["Title"], fontName="Helvetica-Bold",
            fontSize=22, leading=26, spaceAfter=4,
        ),
        "subtitle": ParagraphStyle(
            "st", parent=base["Normal"], fontName="Helvetica",
            fontSize=10.5, leading=14, textColor=colors.HexColor("#444444"),
        ),
        "h2": ParagraphStyle(
            "h2", parent=base["Heading2"], fontName="Helvetica-Bold",
            fontSize=13, leading=16, spaceBefore=16, spaceAfter=6,
        ),
        "item": ParagraphStyle(
            "it", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=11, leading=14, spaceAfter=1,
        ),
        "meta": ParagraphStyle(
            "m", parent=base["Normal"], fontName="Helvetica",
            fontSize=8.5, leading=11, textColor=colors.HexColor("#666666"),
        ),
        "body": ParagraphStyle(
            "b", parent=base["Normal"], fontName="Helvetica",
            fontSize=9.5, leading=13, alignment=TA_LEFT, spaceBefore=3,
        ),
        "quote": ParagraphStyle(
            "q", parent=base["Normal"], fontName="Courier",
            fontSize=8.5, leading=11, leftIndent=10,
            textColor=colors.HexColor("#333333"),
        ),
        "cite": ParagraphStyle(
            "c", parent=base["Normal"], fontName="Helvetica",
            fontSize=7.5, leading=10, leftIndent=10,
            textColor=colors.HexColor("#2A5DB0"),
        ),
        "fix": ParagraphStyle(
            "f", parent=base["Normal"], fontName="Helvetica-Bold",
            fontSize=9.5, leading=13, leftIndent=10,
            textColor=colors.HexColor("#1B6B30"),
        ),
    }


def _esc(text: str) -> str:
    return (
        str(text).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    )


class ReportAgent:
    name = "report"

    def __init__(self, emit: EmitFn | None = None):
        self._emit = emit or (lambda e: None)

    def render_pdf(self, report: ClearanceReport, out_path: str | Path) -> Path:
        path = Path(out_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        s = _styles()

        doc = SimpleDocTemplate(
            str(path), pagesize=LETTER,
            leftMargin=0.85 * inch, rightMargin=0.85 * inch,
            topMargin=0.75 * inch, bottomMargin=0.75 * inch,
            title=f"Script Clearance Report — {report.script.title}",
            author="CLEARCUT",
        )

        flow: list = []
        flow += self._cover(report, s)
        flow.append(PageBreak())
        flow += self._findings(report, s)

        doc.build(flow, onFirstPage=_footer, onLaterPages=_footer)

        self._emit(
            AgentEvent(
                agent=self.name, phase="done",
                message=f"Clearance report written to {path.name}",
                payload={"path": str(path), "findings": len(report.findings)},
            )
        )
        return path

    # ------------------------------------------------------------------ #
    def _cover(self, r: ClearanceReport, s) -> list:
        m = r.script
        draft = " · ".join(x for x in [m.draft_label and f"{m.draft_label} draft", m.draft_date] if x)

        out = [
            Paragraph("SCRIPT CLEARANCE REPORT", s["title"]),
            Paragraph(
                f"{_esc(m.title)}"
                + (f" — {_esc(m.author)}" if m.author else "")
                + (f"<br/>{_esc(draft)}" if draft else "")
                + f"<br/>{m.page_count} pages · report {r.report_id}",
                s["subtitle"],
            ),
            Spacer(1, 10),
            HRFlowable(width="100%", color=colors.HexColor("#CCCCCC")),
            Spacer(1, 14),
        ]

        counts = r.counts_by_verdict()
        blocking = len(r.blocking_items())

        # The headline a producer actually needs.
        status = (
            f"<b>{blocking} item{'s' if blocking != 1 else ''} must be resolved "
            f"before an E&amp;O policy can bind.</b>"
            if blocking
            else "<b>No blocking items. This draft is clear for E&amp;O submission.</b>"
        )
        out += [Paragraph(status, s["body"]), Spacer(1, 12)]

        rows = [["Ruling", "Items"]]
        for v in _VERDICT_ORDER:
            rows.append([_LABEL[v], str(counts.get(v.value, 0))])
        rows.append(["TOTAL FLAGGED", str(len(r.findings))])

        table = Table(rows, colWidths=[3.0 * inch, 0.9 * inch], hAlign="LEFT")
        style = [
            ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
            ("FONTNAME", (0, 1), (-1, -1), "Helvetica"),
            ("FONTSIZE", (0, 0), (-1, -1), 9.5),
            ("BOTTOMPADDING", (0, 0), (-1, -1), 6),
            ("TOPPADDING", (0, 0), (-1, -1), 6),
            ("LINEBELOW", (0, 0), (-1, 0), 0.8, colors.HexColor("#888888")),
            ("LINEABOVE", (0, -1), (-1, -1), 0.8, colors.HexColor("#888888")),
            ("FONTNAME", (0, -1), (-1, -1), "Helvetica-Bold"),
            ("ALIGN", (1, 0), (1, -1), "RIGHT"),
        ]
        for i, v in enumerate(_VERDICT_ORDER, start=1):
            style.append(("TEXTCOLOR", (0, i), (0, i), _COLOR[v]))
        table.setStyle(TableStyle(style))
        out += [table, Spacer(1, 16)]

        out += [
            Paragraph(
                f"Generated in {r.elapsed_seconds:.0f} seconds · "
                f"{r.parallel_calls} live web verifications · "
                f"{r.gemini_calls} model calls",
                s["meta"],
            ),
            Spacer(1, 14),
            Paragraph(
                "This report identifies material in the screenplay that may require "
                "clearance, licensing or revision before production. Every ruling is "
                "supported by the sources cited beneath it. It is prepared to support "
                "review by production counsel and does not itself constitute legal advice.",
                s["meta"],
            ),
        ]
        return out

    def _findings(self, r: ClearanceReport, s) -> list:
        out = [Paragraph("FINDINGS", s["h2"])]
        grouped = {v: [] for v in _VERDICT_ORDER}
        for f in r.findings:
            if f.adjudication:
                grouped[f.adjudication.verdict].append(f)

        for verdict in _VERDICT_ORDER:
            group = grouped[verdict]
            if not group:
                continue
            group.sort(key=lambda f: (f.item.locations[0].page if f.item.locations else 0))

            out.append(Spacer(1, 8))
            out.append(
                Paragraph(
                    f'<font color="{_COLOR[verdict].hexval()}">'
                    f"<b>{_LABEL[verdict]}</b></font> — {len(group)} item"
                    f"{'s' if len(group) != 1 else ''}",
                    s["h2"],
                )
            )
            out.append(HRFlowable(width="100%", color=colors.HexColor("#DDDDDD")))

            for f in group:
                out.append(self._one(f, s))
        return out

    def _one(self, f, s):
        item, adj = f.item, f.adjudication
        block: list = [Spacer(1, 9)]

        pages = ", ".join(
            f"p{l.page}" + (f" sc.{l.scene_number}" if l.scene_number else "")
            for l in item.locations[:6]
        )
        block.append(Paragraph(_esc(item.value), s["item"]))
        block.append(
            Paragraph(
                f"{item.category.value.replace('_', ' ')} · {pages}"
                + (f" · risk {adj.risk.value}" if adj else "")
                + (f" · {_esc(adj.rule_applied)}" if adj and adj.rule_applied else ""),
                s["meta"],
            )
        )

        if item.locations:
            block.append(Paragraph(f'"{_esc(item.locations[0].quote[:200])}"', s["quote"]))

        if adj:
            block.append(Paragraph(_esc(adj.rationale), s["body"]))
            if adj.requires_license_from:
                block.append(
                    Paragraph(
                        f"Licence required from: {_esc(adj.requires_license_from)}",
                        s["body"],
                    )
                )
            for c in adj.citations[:3]:
                block.append(
                    Paragraph(f"› {_esc((c.title or c.url)[:96])}<br/>{_esc(c.url[:110])}", s["cite"])
                )

        sub = f.substitution
        if sub and sub.verified_clear:
            block.append(
                Paragraph(
                    f"RECOMMENDED REPLACEMENT: {_esc(sub.proposed)} — re-cleared and "
                    f"verified {sub.verification_verdict.value if sub.verification_verdict else 'clear'}"
                    + (
                        f" (rejected: {_esc(', '.join(sub.rejected_candidates))})"
                        if sub.rejected_candidates else ""
                    ),
                    s["fix"],
                )
            )
        elif sub and sub.rejected_candidates:
            block.append(
                Paragraph(
                    f"No verified replacement found. Tried: "
                    f"{_esc(', '.join(sub.rejected_candidates))}.",
                    s["body"],
                )
            )

        # Keep an item and its sources on one page where possible.
        return KeepTogether(block)


def _footer(canvas, doc):
    canvas.saveState()
    canvas.setFont("Helvetica", 7.5)
    canvas.setFillColor(colors.HexColor("#888888"))
    canvas.drawString(0.85 * inch, 0.5 * inch, "CLEARCUT — automated script clearance")
    canvas.drawRightString(LETTER[0] - 0.85 * inch, 0.5 * inch, f"Page {doc.page}")
    canvas.restoreState()
