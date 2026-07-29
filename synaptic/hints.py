"""Personal recovery hints and the knowledge graph built from them.

A *hint set* is the operator's structured memory of a wallet they own: fragments
they think were in the password, how strongly they believe each one, and how the
fragments were joined (delimiters). It is loaded from a local JSON file (YAML is
also accepted when PyYAML is installed) that ``.gitignore`` keeps out of version
control - a hint set is candidate password material and is treated as sensitive.

``build_graph`` writes the hint set into the SynapCores property graph, which
then becomes the single source of truth that :mod:`synaptic.generate` reads back
via GraphRAG. Free-text memories can be enriched into discrete hints using the
embedded LLM's entity extraction, falling back to a deterministic tokenizer when
the model is cold or unavailable.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field

from .client import SynapCoresClient

REQUIRED_WEIGHT = 3  # weight >= this marks a hint as a required tokenlist line

# Kinds that carry a literal fragment and should get case variants.
_CASED_KINDS = {"word", "name", "place"}


@dataclass
class Hint:
    """One remembered password fragment."""

    text: str
    kind: str = "word"  # word|name|place|literal|wildcard|prefix|suffix
    weight: int = 1  # >= REQUIRED_WEIGHT -> required line
    position: int | None = None  # 1-indexed anchor; None = order by weight

    @property
    def required(self) -> bool:
        return self.weight >= REQUIRED_WEIGHT

    @property
    def cased(self) -> bool:
        return self.kind in _CASED_KINDS


@dataclass
class HintSet:
    """Everything known about one wallet's likely password."""

    wallet_label: str
    wallet_type: str = "multibit-classic"
    delimiters: list[str] = field(default_factory=lambda: [""])
    hints: list[Hint] = field(default_factory=list)
    notes: str = ""

    @classmethod
    def from_dict(cls, raw: dict) -> HintSet:
        hints = [
            Hint(
                text=str(h["text"]),
                kind=str(h.get("kind", "word")),
                weight=int(h.get("weight", 1)),
                position=h.get("position"),
            )
            for h in raw.get("hints", raw.get("memory", []))
            if str(h.get("text", "")).strip()
        ]
        return cls(
            wallet_label=str(raw.get("wallet_label", "wallet")),
            wallet_type=str(raw.get("wallet_type", "multibit-classic")),
            delimiters=list(raw.get("delimiters", [""])) or [""],
            hints=hints,
            notes=str(raw.get("notes", "")),
        )


def load_hints(path: str) -> HintSet:
    """Load a hint set from a ``.json`` file (or ``.yml`` if PyYAML is present)."""
    with open(path, encoding="utf-8") as fh:
        text = fh.read()
    if path.endswith((".yml", ".yaml")):
        try:
            import yaml  # type: ignore
        except ImportError as exc:  # pragma: no cover - optional dependency
            raise RuntimeError(
                "YAML hint files need PyYAML (pip install pyyaml); or use a .json hint file"
            ) from exc
        raw = yaml.safe_load(text)
    else:
        raw = json.loads(text)
    return HintSet.from_dict(raw)


def _cypher_str(value: str) -> str:
    """Escape a string for a Cypher single-quoted literal (value only, no quotes).

    Centralizes graph-label escaping so both the write and read paths use one
    tested routine instead of ad hoc ``replace`` calls.
    """
    return value.replace("\\", "\\\\").replace("'", "''")


_MAX_FRAGMENT_LEN = 64


def _valid_fragment(value: str) -> bool:
    """Accept only sane password-fragment strings from model output."""
    return bool(value) and len(value) <= _MAX_FRAGMENT_LEN and value.isprintable()


# ---------------------------------------------------------------------------
# Free-text -> hints
# ---------------------------------------------------------------------------

_YEAR_RE = re.compile(r"\b(19|20)\d{2}\b")
_WORD_RE = re.compile(r"[A-Za-z]{3,}")
_STOPWORDS = {
    "the",
    "and",
    "was",
    "were",
    "with",
    "that",
    "this",
    "have",
    "had",
    "for",
    "from",
    "some",
    "around",
    "about",
    "think",
    "maybe",
    "born",
    "named",
    "our",
    "his",
    "her",
    "their",
    "when",
    "where",
    "what",
    "wallet",
    "password",
}


def enrich_freeform(client: SynapCoresClient | None, text: str, weight: int = 1) -> list[Hint]:
    """Turn a free-text memory into discrete hints.

    Tries the embedded LLM's entity extraction first (names, places, dates map to
    weightier, cased hints). Always folds in a deterministic pass so the result is
    useful even when the model returns nothing, then deduplicates.
    """
    hints: list[Hint] = []
    seen: set = set()

    def add(fragment: str, kind: str, w: int) -> None:
        key = (fragment.lower(), kind)
        if fragment and key not in seen:
            seen.add(key)
            hints.append(Hint(text=fragment, kind=kind, weight=w))

    if client is not None:
        for ent in client.extract_entities(text):
            value = str(ent.get("text") or ent.get("value") or "").strip()
            label = str(ent.get("type") or ent.get("label") or "").lower()
            if not _valid_fragment(value):
                continue
            if any(k in label for k in ("person", "name", "org")):
                add(value, "name", weight + 1)
            elif any(k in label for k in ("gpe", "loc", "place", "city")):
                add(value, "place", weight + 1)
            elif any(k in label for k in ("date", "time", "year")):
                add(value, "literal", weight)

    for year in _YEAR_RE.finditer(text):
        add(year.group(0), "literal", weight)
    for match in _WORD_RE.finditer(text):
        word = match.group(0)
        if word.lower() not in _STOPWORDS:
            add(word, "word", weight)
    return hints


# ---------------------------------------------------------------------------
# Hint set -> property graph
# ---------------------------------------------------------------------------


def build_graph(client: SynapCoresClient, hint_set: HintSet) -> str:
    """Write a hint set into the implicit property graph.

    Shape::

        (:Wallet {label})-[:REMEMBERS {weight}]->(:Hint {text, kind, weight})

    Returns the wallet node id. Existing hint nodes for the same wallet label are
    cleared first so the graph reflects the current hint set.
    """
    label = _cypher_str(hint_set.wallet_label)
    # Clear any prior graph for this wallet so re-ingesting is idempotent.
    client.graph_match(
        f"MATCH (w:Wallet {{label: '{label}'}})-[:REMEMBERS]->(h:Hint) DETACH DELETE h"
    )
    client.graph_match(f"MATCH (w:Wallet {{label: '{label}'}}) DETACH DELETE w")

    wallet_id = client.graph_add_node(
        ["Wallet"], {"label": hint_set.wallet_label, "wallet_type": hint_set.wallet_type}
    )
    for hint in hint_set.hints:
        hint_id = client.graph_add_node(
            ["Hint"],
            {
                "text": hint.text,
                "kind": hint.kind,
                "weight": hint.weight,
                "position": hint.position if hint.position is not None else 0,
            },
        )
        client.graph_add_edge(wallet_id, hint_id, "REMEMBERS", {"weight": hint.weight})
    return wallet_id


def read_hints_from_graph(client: SynapCoresClient, wallet_label: str) -> list[Hint]:
    """GraphRAG read-back: recover the hint list for a wallet from the graph."""
    label = _cypher_str(wallet_label)
    result = client.graph_match(
        f"MATCH (w:Wallet {{label: '{label}'}})-[:REMEMBERS]->(h:Hint) "
        "RETURN h ORDER BY h.weight DESC"
    )
    hints: list[Hint] = []
    for row in result.get("rows", []):
        node = row[0]
        props = node.get("properties", {}) if isinstance(node, dict) else {}
        pos = props.get("position")
        hints.append(
            Hint(
                text=str(props.get("text", "")),
                kind=str(props.get("kind", "word")),
                weight=int(props.get("weight", 1)),
                position=int(pos) if pos else None,
            )
        )
    return hints
