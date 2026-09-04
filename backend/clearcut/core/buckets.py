"""
How a production reads a clearance list.

The seventeen categories are the right vocabulary for the legal theory but the
wrong vocabulary for the person doing the review. Nobody sits down to check
"logo_signage" — they check the brands. And the work genuinely splits by
department: names go to the writer, places go to locations, music and artwork go
to the rights coordinator, and the contact details are a props and continuity
problem.

So the review groups by who has to act on it, not by which statute applies.
"""

from __future__ import annotations

from dataclasses import dataclass

from clearcut.core.models import ClearanceCategory as C


@dataclass(frozen=True)
class Bucket:
    id: str
    name: str
    blurb: str
    categories: tuple[C, ...]


BUCKETS: tuple[Bucket, ...] = (
    Bucket(
        "people",
        "People",
        "Character names and references to real people. Cleared on whether a real, "
        "identifiable person could claim the character is them.",
        (C.CHARACTER_NAME, C.REAL_PERSON),
    ),
    Bucket(
        "companies",
        "Businesses & brands",
        "Trade names, products and institutions. A real mark shown neutrally is "
        "usually fine; the same mark shown doing something wrong is not.",
        (C.BUSINESS_NAME, C.BRAND_PRODUCT, C.ORGANIZATION, C.LOGO_SIGNAGE),
    ),
    Bucket(
        "places",
        "Places",
        "Addresses and named venues. The question is whether it resolves to a real, "
        "occupied premises.",
        (C.ADDRESS, C.LOCATION_NAME),
    ),
    Bucket(
        "contact",
        "Numbers, domains & plates",
        "Anything a viewer could dial, visit or look up. These must not reach a real "
        "person, so they are held to a stricter standard than names.",
        (C.PHONE_NUMBER, C.URL_DOMAIN, C.EMAIL, C.LICENSE_PLATE),
    ),
    Bucket(
        "rights",
        "Music, artwork & clips",
        "Material owned by someone else. These usually need a licence rather than a "
        "revision, and the licence is often two separate grants.",
        (C.MUSIC_CUE, C.ARTWORK, C.FILM_TV_CLIP, C.PRINT_MEDIA),
    ),
    Bucket(
        "depiction",
        "Depiction risk",
        "Entities the script portrays in a way their owner would object to.",
        (C.DEPICTION_RISK,),
    ),
)

_BY_CATEGORY: dict[str, str] = {
    c.value: b.id for b in BUCKETS for c in b.categories
}

# Anything a future category forgets to map lands here rather than vanishing.
FALLBACK = "other"


def bucket_for(category: str) -> str:
    return _BY_CATEGORY.get(category, FALLBACK)


def taxonomy() -> list[dict]:
    out = [
        {
            "id": b.id,
            "name": b.name,
            "blurb": b.blurb,
            "categories": [c.value for c in b.categories],
        }
        for b in BUCKETS
    ]
    out.append(
        {
            "id": FALLBACK,
            "name": "Other",
            "blurb": "Items that do not fall into the groups above.",
            "categories": [],
        }
    )
    return out
