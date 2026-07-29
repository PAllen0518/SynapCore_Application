"""Numeric shape features for a candidate password.

Two consumers: AutoML (whose feature engineering only takes numeric columns, so
every feature here is an int) and the heuristic ranker (a cheap structural prior
over the same numbers).

Features are what we store instead of the plaintext, so coverage and ranking can
persist without ever keeping a candidate password.
"""

from __future__ import annotations

from collections.abc import Sequence

FEATURE_COLUMNS: list[str] = [
    "length",
    "ntok",
    "has_digit",
    "has_upper",
    "has_special",
    "n_letters",
    "n_digits",
]


def _segment_count(candidate: str, delimiters: Sequence[str]) -> int:
    """Count fragments, splitting on any non-empty remembered delimiter."""
    seps = [d for d in delimiters if d]
    if not seps:
        return 1
    parts = [candidate]
    for sep in seps:
        parts = [piece for chunk in parts for piece in chunk.split(sep)]
    return max(1, len([p for p in parts if p]))


def extract(candidate: str, delimiters: Sequence[str] = ("",)) -> dict[str, int]:
    """Return the numeric feature dict for one candidate."""
    n_letters = sum(c.isalpha() for c in candidate)
    n_digits = sum(c.isdigit() for c in candidate)
    n_special = sum((not c.isalnum()) for c in candidate)
    return {
        "length": len(candidate),
        "ntok": _segment_count(candidate, delimiters),
        "has_digit": int(n_digits > 0),
        "has_upper": int(any(c.isupper() for c in candidate)),
        "has_special": int(n_special > 0),
        "n_letters": n_letters,
        "n_digits": n_digits,
    }


def vector(candidate: str, delimiters: Sequence[str] = ("",)) -> list[int]:
    """Feature values in FEATURE_COLUMNS order."""
    feats = extract(candidate, delimiters)
    return [feats[col] for col in FEATURE_COLUMNS]
