"""
Whole-script depiction pass.

Breakdown reads scenes in parallel, which is fast and accurate for FINDING
subjects but structurally blind to how the script as a whole treats them. In
THE LONG ODDS, scene 4 shows a man reading a printout with a hospital's name on
it. Read alone that is neutral. Read against scenes 3, 5 and 6 it is a forged
medical record, and the hospital is being shown as the source of falsified
documents.

That distinction is not a detail. Exposure is the product of two things:
whether a real referent exists, and how the script treats it. Getting the
second half wrong turns a defamation risk into a CLEAR.

WHY THIS IS TWO STEPS. Asking one call to judge every subject against a full
screenplay was measured to be unreliable in both directions. Over repeated runs
of the identical script it scored between 62% and 100% against the fixture,
with the number of subjects called negative swinging between 4 and 23. Neither
majority nor union of several passes fixed it: majority was stable but wrong,
because shallow passes outvoted thorough ones, and union inherited any single
over-inclusive pass and marked the protagonist's own garage as negative.

The instability is in the task shape, not the sampling. Twenty-odd
simultaneous judgements against a long text is too much to hold at once.

So the work is split. The first call reads the script and writes down what
actually happens: each wrongful act, who commits it, and which named entities
are caught up in it and in what role. That is a small, focused output. The
second call judges subjects against that written finding rather than
re-deriving the plot for each one, which turns the hard step into a lookup and
gives the reviewer a reason they can check.
"""

from __future__ import annotations

import logging
import re
from typing import Callable

from pydantic import BaseModel, Field

from clearcut.core.models import AgentEvent, ClearableItem
from clearcut.core.screenplay import ParsedScreenplay
from clearcut.services.gemini_client import get_gemini

logger = logging.getLogger(__name__)

EmitFn = Callable[[AgentEvent], None]

# --------------------------------------------------------------------------- #
# Step 1: what actually happens in this script
# --------------------------------------------------------------------------- #
FINDINGS_SYSTEM = """You read a screenplay and write down the wrongdoing in it, for a
motion picture clearance review. You are not judging anything yet. You are recording
what the finished film would show an audience.

List every wrongful act the script depicts: crime, fraud, forgery, conspiracy,
violence, corruption, professional misconduct, negligence, or the producing and
authenticating of falsified documents.

An act has to be genuinely WRONGFUL. Ordinary conflict is not wrongdoing: being late,
owing money, arguing, lying to a friend, drinking, or behaving badly are not acts for
this purpose unless they are part of a crime or a professional breach. If you would not
expect a lawyer to care, leave it out. Over-recording harmless behaviour puts innocent
characters on a clearance report.

Include acts that are DESCRIBED IN DIALOGUE or established by the plot, not only ones
staged on screen. A scheme a character explains, or one the audience is shown the
evidence of, is depicted just as surely as one performed in front of the camera. An
ongoing operation ("buys salvage titles, doesn't ask questions") is an act. So is a
pattern a character uncovers ("eleven cars, same adjuster, same doctor").

For each act, record:
- what happens, in one plain sentence
- who does it, by character name
- every NAMED entity caught up in it, and the role it plays

Roles:
  perpetrator  commits or directs the act
  instrument   its name, premises, domain, paperwork or staff are used to carry it out
  employer     a named company or institution the perpetrator is said to work for
  venue        the named place the ACT ITSELF happens. Record BOTH the building or
               business name AND any street address given for it, as separate
               entries. "the old Harrow building on 400 Ninth" is two venues.
  victim       harmed by it, without their name being attached to the wrongdoing
  misused      their name, signature, credentials or likeness are forged, faked or
               attached to the act without their involvement
  opposing     works against the wrongdoing: investigates it, exposes it, or refuses
               to take part

Record a location as venue ONLY when the wrongful act happens there. A place where a
scene merely takes place is not a venue. A character's own home or workplace is not a
venue because they are in it.

Record a character as "opposing" when the script has them uncovering or resisting the
act, and record their workplace as opposing too. Being the protagonist of a story about
fraud is not taking part in fraud.

Be exhaustive about named entities. Every act usually touches several, and an entity
you leave out is one that never gets reviewed. If a character is introduced as working somewhere
("Ferris at NORTHWIND MUTUAL"), record that employer. If a document carries an
institution's name, record that institution as instrument. RESOLVE ROLE REFERENCES. When a line names a role rather than a person ("the same
adjuster", "the doctor", "whoever signed it"), work out which character holds that role
earlier in the script and record THAT CHARACTER plus the employer they were introduced
with. A script that establishes "Ferris at NORTHWIND MUTUAL" in one scene and refers to
"the same adjuster" three scenes later has implicated both Ferris and Northwind Mutual,
and this is the single most commonly missed connection because the two halves never
appear in the same scene.

Record only what the script actually depicts. Do not invent acts."""


class _Involvement(BaseModel):
    entity: str = Field(description="The named entity, exactly as the script writes it")
    role: str = Field(description="perpetrator | instrument | employer | venue | victim")


class _Act(BaseModel):
    what: str = Field(description="What happens, one plain sentence")
    who: str = Field(default="", description="Character who does it")
    involves: list[_Involvement] = Field(default_factory=list)


# --------------------------------------------------------------------------- #
# Step 2: judge the subjects against that finding
# --------------------------------------------------------------------------- #
JUDGE_SYSTEM = """You decide, for motion picture clearance, whether a screenplay
portrays each subject in a way its owner, or a real person of that name, would object to.

You are given a written finding of the wrongdoing in the script, and a list of subjects.
Judge each subject against the finding. Do not re-read the plot; the finding is what the
film shows.

Mark NEGATIVE when the finding places the subject in any of these roles:
  perpetrator, instrument, employer, venue, or misused.

"Misused" counts as negative even though the subject is wronged rather than at fault.
The film puts their name on the fraud, and a real person or company of that name would
object to being shown that way. Their innocence in the story does not remove the
exposure.

A subject recorded as "opposing" is NEUTRAL even if it appears elsewhere in the
finding, because the film shows it resisting the wrongdoing rather than doing it. The
same is true of anything recorded only as victim, where the subject is harmed but its
name is not attached to the act.

An entity is negative even when no character criticises it. An audience does not
separate an employee's conduct from the employer whose name was attached to them, and
seeing an institution's paperwork forged is seeing that institution's name misused.

Mark NEUTRAL when:
  - the subject does not appear in the finding at all
  - the subject appears only as victim, or only as opposing
  - the subject is set dressing or an incidental mention

Being adjacent to a wrongdoer is not enough. The protagonist's own workplace is neutral
unless the finding says it was used to carry something out.

Give one entry per subject. The reason must cite the act from the finding, in one line."""


class _Judgement(BaseModel):
    subject: str
    negative: bool
    reason: str = Field(default="", description="One line, citing the act")


class DepictionAgent:
    name = "depiction"

    def __init__(self, emit: EmitFn | None = None):
        self._emit = emit or (lambda e: None)

    def run(
        self, script: ParsedScreenplay, items: list[ClearableItem]
    ) -> list[ClearableItem]:
        if not items:
            return items

        acts = self._findings(script, items)
        if acts is None:
            self._emit(
                AgentEvent(
                    agent=self.name, phase="error",
                    message="Could not read the script's wrongdoing; per-scene flags retained",
                )
            )
            return items

        self._emit(
            AgentEvent(
                agent=self.name,
                phase="findings",
                message=f"Read {len(acts)} wrongful act(s) from the script",
                payload={"acts": [a.what for a in acts]},
            )
        )

        judged = self._judge(acts, items)
        if judged is None:
            self._emit(
                AgentEvent(
                    agent=self.name, phase="error",
                    message="Depiction judgement unavailable; per-scene flags retained",
                )
            )
            return items

        # The roles the findings recorded are authoritative. They are an explicit,
        # checkable statement of what the film shows, so a subject the findings
        # place in a wrongful role is negative whether or not the judging call
        # happened to return an entry for it. Leaving that to the judge alone
        # meant an omitted subject silently kept its stale per-scene flag, which
        # is how the antagonist came back neutral in one draft while the findings
        # named him the perpetrator.
        roles = self._roles(acts)
        changed = 0
        for it in items:
            key = _key(it.value)
            role_verdict = _from_roles(roles.get(key))
            j = judged.get(key)

            if role_verdict is not None:
                negative = role_verdict
                reason = j.reason if (j and j.negative == negative) else _role_reason(roles[key])
            elif j is not None:
                negative = j.negative
                reason = j.reason
            else:
                continue

            if negative != it.is_depicted_negatively:
                changed += 1
            it.is_depicted_negatively = negative
            if negative and reason.strip():
                it.context = (it.context or "") + f" | Depiction: {reason.strip()}"

        neg = sum(1 for i in items if i.is_depicted_negatively)
        self._emit(
            AgentEvent(
                agent=self.name,
                phase="done",
                message=(
                    f"{neg} of {len(items)} subjects depicted negatively "
                    f"({changed} reassessed against the full script)"
                ),
                payload={"negative": neg, "changed": changed, "total": len(items)},
            )
        )
        return items

    # ------------------------------------------------------------------ #
    def _findings(
        self, script: ParsedScreenplay, items: list[ClearableItem]
    ) -> list[_Act] | None:
        # The subject list goes in so entities come back under the same names.
        # Without it the step writes whichever form the scene used, and a
        # finding naming "Cortland" never connects to the subject
        # "Cortland Voss", which silently drops the antagonist from the review.
        known = "\n".join(f"- {it.value}" for it in items)
        prompt = (
            f"SCREENPLAY\n{'=' * 60}\n{script.raw[:120_000]}\n{'=' * 60}\n\n"
            f"SUBJECTS ALREADY IDENTIFIED IN THIS SCRIPT:\n{known}\n\n"
            "Write down the wrongdoing this script depicts. When an entity you "
            "record is one of the subjects listed above, name it EXACTLY as it "
            "appears in that list, not as the scene happens to write it."
        )
        try:
            raw = get_gemini().generate_structured(
                prompt=prompt, schema=list[_Act], system=FINDINGS_SYSTEM,
                temperature=0.0, thinking_budget=0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Findings pass failed: %s", exc)
            return None
        out: list[_Act] = []
        for row in raw or []:
            try:
                out.append(_Act.model_validate(row))
            except Exception:  # noqa: BLE001, S112
                continue
        return out

    @staticmethod
    def _roles(acts: list[_Act]) -> dict[str, set[str]]:
        out: dict[str, set[str]] = {}
        for a in acts:
            for inv in a.involves:
                out.setdefault(_key(inv.entity), set()).add(inv.role.strip().lower())
        return out

    def _judge(
        self, acts: list[_Act], items: list[ClearableItem]
    ) -> dict[str, _Judgement] | None:
        finding = "\n".join(
            f"- {a.what}"
            + (f" (by {a.who})" if a.who else "")
            + "".join(f"\n    {i.role}: {i.entity}" for i in a.involves)
            for a in acts
        ) or "(no wrongdoing recorded)"

        listing = "\n".join(f"- {it.value}  [{it.category.value}]" for it in items)
        prompt = (
            f"WHAT THE FILM SHOWS\n{'=' * 60}\n{finding}\n{'=' * 60}\n\n"
            f"SUBJECTS TO JUDGE ({len(items)}):\n{listing}\n\n"
            "Judge every subject listed against the finding above."
        )
        try:
            raw = get_gemini().generate_structured(
                prompt=prompt, schema=list[_Judgement], system=JUDGE_SYSTEM,
                temperature=0.0, thinking_budget=0,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("Depiction judgement failed: %s", exc)
            return None
        judged: dict[str, _Judgement] = {}
        for row in raw or []:
            try:
                j = _Judgement.model_validate(row)
            except Exception:  # noqa: BLE001, S112
                continue
            judged[_key(j.subject)] = j
        return judged


# Roles that mean the film shows the subject caught up in the wrongdoing.
_NEGATIVE_ROLES = {"perpetrator", "instrument", "employer", "venue", "misused"}
# Roles that do not, on their own, create exposure.
_NEUTRAL_ROLES = {"victim", "opposing"}


def _from_roles(roles: set[str] | None) -> bool | None:
    """Decide from the recorded roles, or None if they do not settle it."""
    if not roles:
        return None
    if roles & _NEGATIVE_ROLES:
        return True
    if roles <= _NEUTRAL_ROLES:
        return False
    return None


def _role_reason(roles: set[str]) -> str:
    named = sorted(roles & _NEGATIVE_ROLES) or sorted(roles)
    return "recorded in the script's wrongdoing as " + ", ".join(named)


def _key(value: str) -> str:
    """Match subjects across steps despite casing and punctuation drift."""
    return re.sub(r"[^a-z0-9]+", "", value.lower())
