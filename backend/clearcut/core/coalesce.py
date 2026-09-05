"""
Post-breakdown coalescing.

Extraction is deliberately over-inclusive — a missed item becomes an uninsurable
film. But over-inclusion produces three artifacts that must not reach a report:

1. Name fragments. A scene naming DESMOND HALE and later "Hale" yields both, and
   researching a bare surname wastes a lookup and duplicates a report row.
2. Generic roles. "Doctor" and "Insurance Adjuster" are occupations, not
   clearable subjects. The extraction prompt forbids them and the model returns
   them anyway, so the guard belongs here where it is deterministic.
3. Cross-category duplicates. ZENITH MOTORS is legitimately both a business name
   and visible signage; it is still one clearance subject.

All three are decided by rule rather than by another model call: the logic is
knowable, and a report that changes between runs is not a legal artifact.
"""

from __future__ import annotations

import re

from clearcut.core.naming import person_words, tokens
from clearcut.core.models import ClearableItem, ClearanceCategory

# --------------------------------------------------------------------------- #
# Generic roles and titles that carry no clearance exposure on their own.
# --------------------------------------------------------------------------- #
_GENERIC = {
    "doctor", "nurse", "surgeon", "physician", "paramedic", "emt",
    "insurance adjuster", "adjuster", "claims adjuster", "agent",
    "cop", "police officer", "officer", "detective", "sergeant", "lieutenant",
    "guard", "security guard", "bartender", "waitress", "waiter", "driver",
    "mechanic", "receptionist", "secretary", "lawyer", "attorney", "judge",
    "man", "woman", "boy", "girl", "kid", "teenager", "stranger", "neighbour",
    "neighbor", "customer", "clerk", "foreman", "boss", "landlord", "tenant",
    "mother", "father", "mom", "dad", "son", "daughter", "brother", "sister",
    "husband", "wife", "voice", "announcer", "reporter", "anchor",
}

# Honorifics stripped before comparing names, so "Dr. Alan Reinholt" and
# "Alan Reinholt" are recognised as the same subject.
_HONORIFIC = re.compile(
    r"^(?:dr|doctor|mr|mrs|ms|miss|prof|professor|rev|sgt|sergeant|lt|"
    r"lieutenant|capt|captain|det|detective|officer|sir|madam)\.?\s+",
    re.IGNORECASE,
)

# Which category wins when the same subject is extracted under several. Ordered
# most legally specific first.
_PRIORITY = [
    ClearanceCategory.BRAND_PRODUCT,
    ClearanceCategory.BUSINESS_NAME,
    ClearanceCategory.ORGANIZATION,
    ClearanceCategory.REAL_PERSON,
    ClearanceCategory.MUSIC_CUE,
    ClearanceCategory.ARTWORK,
    ClearanceCategory.FILM_TV_CLIP,
    ClearanceCategory.PRINT_MEDIA,
    ClearanceCategory.CHARACTER_NAME,
    ClearanceCategory.ADDRESS,
    ClearanceCategory.URL_DOMAIN,
    ClearanceCategory.EMAIL,
    ClearanceCategory.PHONE_NUMBER,
    ClearanceCategory.LICENSE_PLATE,
    ClearanceCategory.LOCATION_NAME,
    ClearanceCategory.LOGO_SIGNAGE,
    ClearanceCategory.DEPICTION_RISK,
]
_RANK = {c: i for i, c in enumerate(_PRIORITY)}

# Categories whose values are personal names, where fragment-merging applies.
_NAME_LIKE = {ClearanceCategory.CHARACTER_NAME, ClearanceCategory.REAL_PERSON}




def coalesce(items: list[ClearableItem]) -> tuple[list[ClearableItem], list[str]]:
    """Merge fragments and duplicates, drop generic roles.

    Returns the surviving items and a human-readable log of what was folded,
    so the decision is auditable rather than silent.
    """
    notes: list[str] = []

    # -- 1. drop generic roles ------------------------------------------- #
    kept: list[ClearableItem] = []
    for it in items:
        if person_words(it.value) in _GENERIC:
            notes.append(f"dropped '{it.value}' — generic role, no clearance subject")
            continue
        kept.append(it)

    # -- 2. merge identical subjects across categories -------------------- #
    by_value: dict[str, list[ClearableItem]] = {}
    for it in kept:
        by_value.setdefault(person_words(it.value), []).append(it)

    merged: list[ClearableItem] = []
    for group in by_value.values():
        if len(group) == 1:
            merged.append(group[0])
            continue
        winner = min(group, key=lambda i: _RANK.get(i.category, 99))
        for other in group:
            if other is winner:
                continue
            winner.locations.extend(other.locations)
            winner.is_depicted_negatively |= other.is_depicted_negatively
            notes.append(
                f"merged '{other.value}' ({other.category.value}) into "
                f"{winner.category.value}"
            )
        merged.append(winner)

    # -- 3. absorb name fragments into their fullest form ----------------- #
    names = [i for i in merged if i.category in _NAME_LIKE]
    # Longest first, so "Desmond Hale" is the absorber and "Hale" the absorbed.
    names.sort(key=lambda i: len(tokens(i.value)), reverse=True)

    absorbed: set[str] = set()
    for i, full in enumerate(names):
        if full.id in absorbed:
            continue
        full_tokens = tokens(full.value)
        if len(full_tokens) < 2:
            continue
        for frag in names[i + 1:]:
            if frag.id in absorbed:
                continue
            frag_tokens = tokens(frag.value)
            # A single-token name fully contained in a longer name is the same
            # person referred to by surname or first name alone.
            if len(frag_tokens) == 1 and frag_tokens < full_tokens:
                full.locations.extend(frag.locations)
                full.is_depicted_negatively |= frag.is_depicted_negatively
                absorbed.add(frag.id)
                notes.append(f"folded '{frag.value}' into '{full.value}'")

    out = [i for i in merged if i.id not in absorbed]

    # Deduplicate locations left by merging, preserving order.
    for it in out:
        seen: set[tuple] = set()
        unique = []
        for loc in it.locations:
            key = (loc.page, loc.scene_number, loc.quote)
            if key in seen:
                continue
            seen.add(key)
            unique.append(loc)
        it.locations = sorted(unique, key=lambda l: (l.page, l.scene_number))

    out.sort(key=lambda i: (i.locations[0].page, i.category.value, i.value.lower()))
    return out, notes
