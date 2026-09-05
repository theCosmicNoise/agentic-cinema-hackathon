"""
Normalising a subject's name.

Four different normalisations grew up in four modules, each correct for its own
job and none of them aware of the others. That is a real hazard rather than
untidiness: the same subject ends up with different keys in different stages,
and a mismatch between two of them is invisible until a finding silently fails
to attach to the item it describes. Exactly that cost the antagonist his
depiction flag in one draft, and cross-paired an email with a character in the
eval harness.

They are collected here so the differences are deliberate and visible. The
behaviour of each is unchanged; only the definition moved.
"""

from __future__ import annotations

import re

# Honorifics are stripped before comparing people, so "Dr. Alan Reinholt" and
# "Alan Reinholt" are recognised as one subject rather than two.
_HONORIFIC = re.compile(
    r"^(?:dr|doctor|mr|mrs|ms|miss|prof|professor|rev|sgt|sergeant|lt|"
    r"lieutenant|capt|captain|det|detective|officer|sir|madam)\.?\s+",
    re.IGNORECASE,
)

_ARTICLE = re.compile(r"^(the|a|an)\s+")


def words(value: str) -> str:
    """Lowercase words, punctuation flattened to spaces.

    The plain form. Use when comparing free text where word boundaries matter.
    """
    s = re.sub(r"[^a-z0-9 ]+", " ", str(value).lower())
    return re.sub(r"\s+", " ", s).strip()


def person_words(value: str) -> str:
    """`words`, with a leading honorific removed.

    Use when the subject may be a person, so a title does not split one name
    into two subjects.
    """
    return words(_HONORIFIC.sub("", str(value).strip()))


def merge_key(value: str) -> str:
    """`words`, with a leading article removed.

    Use when deciding whether two extracted mentions are the same subject:
    "The Godfather" and "Godfather" are one film, not two.
    """
    return _ARTICLE.sub("", words(value))


def identity(value: str) -> str:
    """Letters and digits only, no spaces.

    The tightest form, for looking one subject up by another stage's spelling
    of it. Deliberately ignores word boundaries so "ZENITH MOTORS" and
    "Zenith  Motors" resolve to the same key.
    """
    return re.sub(r"[^a-z0-9]+", "", str(value).lower())


def tokens(value: str, min_length: int = 2) -> set[str]:
    """Significant words, for overlap comparisons."""
    return {t for t in words(value).split() if len(t) >= min_length}
