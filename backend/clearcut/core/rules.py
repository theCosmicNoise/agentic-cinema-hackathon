"""
Deterministic clearance rules.

Not every item needs a web lookup. A clearance house does not research whether
555-0142 is somebody's real phone number — it knows the block is reserved. A
film clip is never "cleared" by searching; it always needs a licence.

Encoding those as rules matters for three reasons: the answers are exact rather
than probabilistic, they cost nothing, and they keep the research budget for the
items where live evidence genuinely decides the outcome.

Each rule returns a verdict directly, or None to mean "this needs research".
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from clearcut.core.models import ClearanceCategory, RiskLevel, Verdict


@dataclass
class RuleOutcome:
    verdict: Verdict
    risk: RiskLevel
    rationale: str
    rule_id: str
    requires_license_from: str | None = None


# --------------------------------------------------------------------------- #
# Phone numbers — the 555 reserved block
# --------------------------------------------------------------------------- #
# NANPA reserves 555-0100 through 555-0199 for fictional use. Any other number
# may reach a real subscriber, who then receives calls from every viewer who
# tries it. This is one of the most common notes on a clearance report.
_PHONE_DIGITS = re.compile(r"\D+")
_RESERVED = re.compile(r"^(?:1)?(?:\d{3})?555 ?01\d{2}$")


def check_phone(value: str) -> RuleOutcome:
    digits = _PHONE_DIGITS.sub("", value)
    normalised = digits[-10:] if len(digits) >= 10 else digits

    if len(normalised) >= 7 and re.match(r"^\d{3}55501\d{2}$|^55501\d{2}$", normalised):
        return RuleOutcome(
            verdict=Verdict.CLEAR,
            risk=RiskLevel.NONE,
            rationale=(
                "Falls inside the 555-0100 to 555-0199 range reserved for fictional "
                "use. Safe to dial on camera."
            ),
            rule_id="NANPA_555_RESERVED_BLOCK",
        )

    return RuleOutcome(
        verdict=Verdict.MUST_CHANGE,
        risk=RiskLevel.HIGH,
        rationale=(
            f"'{value}' sits outside the 555-0100 to 555-0199 reserved block and may "
            "route to a live subscriber. Standard practice is to replace it with a "
            "number in the reserved range."
        ),
        rule_id="NANPA_555_RESERVED_BLOCK",
    )


# --------------------------------------------------------------------------- #
# Film and television clips
# --------------------------------------------------------------------------- #
def check_film_clip(value: str) -> RuleOutcome:
    return RuleOutcome(
        verdict=Verdict.LICENSE_REQUIRED,
        risk=RiskLevel.HIGH,
        rationale=(
            f"On-screen use of '{value}' requires a clip licence from the rights "
            "holder. Depending on what is visible or audible this can also trigger "
            "separate music, guild residual and on-screen performer obligations."
        ),
        rule_id="CLIP_LICENCE_REQUIRED",
        requires_license_from=f"Rights holder / distributor of {value}",
    )


# --------------------------------------------------------------------------- #
# Registry — which categories are decided by rule, which need evidence
# --------------------------------------------------------------------------- #
_DETERMINISTIC = {
    ClearanceCategory.PHONE_NUMBER: check_phone,
    ClearanceCategory.FILM_TV_CLIP: check_film_clip,
}

# Categories where a live lookup is the whole point.
RESEARCH_REQUIRED = {
    ClearanceCategory.CHARACTER_NAME,
    ClearanceCategory.BUSINESS_NAME,
    ClearanceCategory.BRAND_PRODUCT,
    ClearanceCategory.ADDRESS,
    ClearanceCategory.LICENSE_PLATE,
    ClearanceCategory.URL_DOMAIN,
    ClearanceCategory.EMAIL,
    ClearanceCategory.MUSIC_CUE,
    ClearanceCategory.ARTWORK,
    ClearanceCategory.PRINT_MEDIA,
    ClearanceCategory.LOGO_SIGNAGE,
    ClearanceCategory.REAL_PERSON,
    ClearanceCategory.ORGANIZATION,
    ClearanceCategory.LOCATION_NAME,
    ClearanceCategory.DEPICTION_RISK,
}


def apply_deterministic_rule(
    category: ClearanceCategory, value: str
) -> RuleOutcome | None:
    """Settle an item by rule, or return None if it needs live research."""
    fn = _DETERMINISTIC.get(category)
    return fn(value) if fn else None
