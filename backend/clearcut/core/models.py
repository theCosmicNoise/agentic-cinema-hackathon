"""
CLEARCUT domain model.

Mirrors the artifact a real script-clearance house (Act One, Marshall+Plumb)
delivers to a production before an E&O carrier will bind coverage. The
vocabulary here is deliberately the industry's, not a generic NLP taxonomy:
judges, insurers and production counsel all read reports in these terms.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any

from pydantic import BaseModel, Field


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ClearanceCategory(str, Enum):
    """
    The classes of material a clearance researcher marks on every page.

    Each class carries a different legal theory (trademark, right of
    publicity, copyright, defamation), which is why triage routes them to
    different research strategies rather than one generic web lookup.
    """

    CHARACTER_NAME = "character_name"        # right of publicity / defamation
    BUSINESS_NAME = "business_name"          # trademark + trade name
    BRAND_PRODUCT = "brand_product"          # trademark, dilution, tarnishment
    PHONE_NUMBER = "phone_number"            # must fall in 555-0100..555-0199
    ADDRESS = "address"                      # must not resolve to a real premises
    LICENSE_PLATE = "license_plate"          # must not be an issued plate
    URL_DOMAIN = "url_domain"                # must not be a registered domain
    EMAIL = "email"                          # must not be a live mailbox
    MUSIC_CUE = "music_cue"                  # sync + master licences, lyrics
    ARTWORK = "artwork"                      # copyright in artwork on camera
    FILM_TV_CLIP = "film_tv_clip"            # clip licence + guild residuals
    PRINT_MEDIA = "print_media"              # masthead trademark
    LOGO_SIGNAGE = "logo_signage"            # trademark in the frame
    REAL_PERSON = "real_person"              # publicity, defamation, life rights
    ORGANIZATION = "organization"            # real institution / agency
    LOCATION_NAME = "location_name"          # real venue depicted
    DEPICTION_RISK = "depiction_risk"        # negative portrayal of a real entity


class Verdict(str, Enum):
    """The four rulings an insurer expects, plus an explicit escalation."""

    CLEAR = "clear"
    CLEAR_WITH_CAUTION = "clear_with_caution"
    MUST_CHANGE = "must_change"
    LICENSE_REQUIRED = "license_required"
    LEGAL_REVIEW = "legal_review"


class RiskLevel(str, Enum):
    NONE = "none"
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"


class ScriptLocation(BaseModel):
    """Where in the screenplay the item appears. Reports are page-cited."""

    page: int = Field(..., description="1-indexed screenplay page")
    scene_number: str | None = Field(None, description="e.g. '14' or 'A14'")
    scene_heading: str | None = Field(None, description="e.g. 'INT. DINER - NIGHT'")
    quote: str = Field(..., description="Verbatim text as it appears on the page")


class ClearableItem(BaseModel):
    """One flagged element awaiting research and adjudication."""

    id: str
    category: ClearanceCategory
    value: str = Field(..., description="Normalised subject, e.g. 'Zenith Motors'")
    locations: list[ScriptLocation] = Field(default_factory=list)
    context: str | None = Field(
        None, description="How the item is used — drives depiction risk"
    )
    is_depicted_negatively: bool = False
    research_plan: str | None = Field(
        None, description="Objective handed to the Research Agent"
    )


class Citation(BaseModel):
    """A source Parallel returned. Every verdict must be traceable to these."""

    url: str
    title: str | None = None
    excerpt: str | None = None
    retrieved_at: datetime = Field(default_factory=_utcnow)


class ResearchEvidence(BaseModel):
    """Output of the Parallel-backed Research Agent for a single item."""

    item_id: str
    objective: str
    queries: list[str] = Field(default_factory=list)
    citations: list[Citation] = Field(default_factory=list)
    findings: str = ""
    processor: str = Field("base", description="Parallel tier used: search|base|pro")
    escalated: bool = Field(
        False, description="True when Search was insufficient and Task API ran"
    )


class Adjudication(BaseModel):
    """The ruling. This is the line that appears in the delivered report."""

    item_id: str
    verdict: Verdict
    risk: RiskLevel
    rationale: str
    rule_applied: str | None = Field(
        None, description="Named industry rule, e.g. 'FCC_555_RESERVED_BLOCK'"
    )
    citations: list[Citation] = Field(default_factory=list)
    requires_license_from: str | None = None


class Substitution(BaseModel):
    """
    A proposed replacement that has itself been re-cleared.

    The verification loop is the point: a human clearance house tells you
    'no'. CLEARCUT proposes a fix and proves the fix is clean.
    """

    item_id: str
    original: str
    proposed: str
    verified_clear: bool = False
    verification_evidence: ResearchEvidence | None = None
    verification_verdict: Verdict | None = None
    attempts: int = 1
    rejected_candidates: list[str] = Field(default_factory=list)


class ClearanceFinding(BaseModel):
    """One fully-processed row: item + evidence + ruling + optional fix."""

    item: ClearableItem
    evidence: ResearchEvidence | None = None
    adjudication: Adjudication | None = None
    substitution: Substitution | None = None


class ScriptMeta(BaseModel):
    title: str = "Untitled"
    author: str | None = None
    draft_label: str | None = Field(
        None, description="Revision colour: White, Blue, Pink, Yellow, Green, Goldenrod"
    )
    draft_date: str | None = None
    page_count: int = 0


class ClearanceReport(BaseModel):
    """The E&O-ready deliverable."""

    report_id: str
    project_id: str
    script: ScriptMeta
    findings: list[ClearanceFinding] = Field(default_factory=list)
    generated_at: datetime = Field(default_factory=_utcnow)
    elapsed_seconds: float = 0.0
    parallel_calls: int = 0
    gemini_calls: int = 0

    def counts_by_verdict(self) -> dict[str, int]:
        out: dict[str, int] = {v.value: 0 for v in Verdict}
        for f in self.findings:
            if f.adjudication:
                out[f.adjudication.verdict.value] += 1
        return out

    def blocking_items(self) -> list[ClearanceFinding]:
        """Items that will stop an E&O policy from binding."""
        blocking = {Verdict.MUST_CHANGE, Verdict.LICENSE_REQUIRED, Verdict.LEGAL_REVIEW}
        return [
            f for f in self.findings
            if f.adjudication and f.adjudication.verdict in blocking
        ]


class LedgerEntry(BaseModel):
    """
    Persistent clearance state for one item across the life of a production.

    This is the product wedge: clearance stops being a document you re-buy on
    every revision and becomes state the production continuously holds.
    """

    item_key: str = Field(..., description="category::normalised_value")
    category: ClearanceCategory
    value: str
    verdict: Verdict
    risk: RiskLevel
    rationale: str
    citations: list[Citation] = Field(default_factory=list)
    first_cleared_draft: str | None = None
    last_verified_draft: str | None = None
    last_verified_at: datetime = Field(default_factory=_utcnow)


class RevisionDiff(BaseModel):
    """What actually changed between two drafts — the re-clearance work order."""

    from_draft: str | None
    to_draft: str
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    unchanged: list[str] = Field(default_factory=list)

    @property
    def reuse_ratio(self) -> float:
        total = len(self.added) + len(self.unchanged)
        return (len(self.unchanged) / total) if total else 0.0


class AgentEvent(BaseModel):
    """Streamed to the UI so a judge can watch the network think."""

    ts: datetime = Field(default_factory=_utcnow)
    agent: str
    phase: str
    message: str
    payload: dict[str, Any] = Field(default_factory=dict)
