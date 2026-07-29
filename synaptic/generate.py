"""GraphRAG candidate generation: hint graph -> btcrecover tokenlist.

Reads the hints for a wallet back out of the SynapCores property graph and turns
them into a btcrecover-style tokenlist that :mod:`synaptic.bitcracker` (and the
CUDA/OpenCL tools) can consume directly.

The tokenlist is built in *ordered* form using position anchors (``^N^token``),
which mirrors how the project's own search lists are written (see ``search38.txt``)
and lets a remembered delimiter be folded between fragments. Each fragment slot
offers its case variants; every non-first slot also offers each candidate
delimiter. Optional hints (weight below the required threshold) additionally get
an empty "skip" alternative so a fragment can be absent without disturbing the
positions of the fragments after it.
"""

from __future__ import annotations

from collections.abc import Sequence

from .hints import Hint

# Kinds emitted verbatim (no case variants, no delimiter folding): btcrecover
# wildcards like %0,4d must reach the parser untouched.
_RAW_KINDS = {"wildcard"}


def case_variants(text: str) -> list[str]:
    """Return de-duplicated case variants of a fragment, original first."""
    out: list[str] = []
    for variant in (text, text.lower(), text.capitalize(), text.upper()):
        if variant and variant not in out:
            out.append(variant)
    return out


def _ordered_hints(hints: Sequence[Hint]) -> list[Hint]:
    """Assign a stable slot order: explicit positions honoured, then weight."""
    positioned = sorted((h for h in hints if h.position), key=lambda h: h.position)
    free = [h for h in hints if not h.position]
    free.sort(key=lambda h: -h.weight)
    return positioned + free


def _slot_tokens(hint: Hint, slot: int, delimiters: Sequence[str]) -> list[str]:
    """The alternative tokens for one fragment slot (1-indexed)."""
    if hint.kind in _RAW_KINDS:
        variants = [hint.text]
        prefixes: Sequence[str] = [""]
    else:
        variants = case_variants(hint.text) if hint.cased else [hint.text]
        # The first slot has nothing before it, so it takes no delimiter.
        prefixes = [""] if slot == 1 else list(dict.fromkeys(delimiters))
    tokens: list[str] = []
    for prefix in prefixes:
        for variant in variants:
            token = prefix + variant
            if token not in tokens:
                tokens.append(token)
    if not hint.required and "" not in tokens:
        tokens.append("")  # allow this fragment to be skipped
    return tokens


def _free_tokens(hint: Hint, delimiters: Sequence[str]) -> list[str]:
    """Alternative tokens for a hint in free (unordered) mode.

    No position anchor; each candidate delimiter is offered as a prefix so the
    checker's permutation can still reconstruct delimited passwords in some order.
    """
    if hint.kind in _RAW_KINDS:
        tokens = [hint.text]
    else:
        variants = case_variants(hint.text) if hint.cased else [hint.text]
        tokens = []
        for prefix in dict.fromkeys(delimiters):
            for variant in variants:
                token = prefix + variant
                if token not in tokens:
                    tokens.append(token)
    return tokens


def generate_tokenlist(
    hints: Sequence[Hint],
    delimiters: Sequence[str] | None = None,
    header: str = "",
    *,
    ordered: bool = True,
) -> str:
    """Build a btcrecover tokenlist string from a list of hints.

    ``ordered=True`` (default) emits position-anchored lines (``^N^token``) that
    reconstruct a known fragment order with delimiters folded between slots.
    ``ordered=False`` emits unanchored lines and lets the checker permute the
    fragments — broader coverage for hint sets whose order is unknown, at the
    cost of a larger candidate set.
    """
    delimiters = list(delimiters) if delimiters else [""]
    lines: list[str] = []
    if header:
        lines += ["# " + ln for ln in header.splitlines()]
    if ordered:
        for slot, hint in enumerate(_ordered_hints(hints), start=1):
            tokens = _slot_tokens(hint, slot, delimiters)
            prefix = "+ " if hint.required else ""
            lines.append(prefix + " ".join(f"^{slot}^{tok}" for tok in tokens))
    else:
        for hint in sorted(hints, key=lambda h: -h.weight):
            tokens = _free_tokens(hint, delimiters)
            prefix = "+ " if hint.required else ""
            lines.append(prefix + " ".join(tokens))
    return "\n".join(lines) + "\n"


def write_tokenlist(
    path: str,
    hints: Sequence[Hint],
    delimiters: Sequence[str] | None = None,
    header: str = "",
    *,
    ordered: bool = True,
) -> str:
    """Write a generated tokenlist to ``path`` and return the text."""
    text = generate_tokenlist(hints, delimiters, header, ordered=ordered)
    with open(path, "w", encoding="utf-8") as fh:
        fh.write(text)
    return text
