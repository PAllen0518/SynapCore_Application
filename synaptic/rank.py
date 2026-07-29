"""Rank candidates so the search tries the plausible ones first.

Two backends share one interface, rank(candidates) -> [(candidate, score)] best
first:

- HeuristicRanker (default): a structural prior over the candidate's shape,
  optionally blended with embedding similarity to "style seeds" (example
  passwords the owner used elsewhere). No training, no GPU.
- AutoMLRanker: trains an in-database SynapCores classifier to tell realistic
  passwords from random strings, then scores each candidate by the model's
  predicted probability.

Ranking only reorders work. It never drops a candidate, so a good password with a
low score is still checked, just later.
"""

from __future__ import annotations

import math
import random
from collections.abc import Sequence

from . import features
from .client import SynapCoresClient

Scored = list[tuple[str, float]]

RANK_TRAIN_TABLE = "sc_rank_train"


def _structural_prior(candidate: str, delimiters: Sequence[str]) -> float:
    """A cheap 0..1 prior favouring realistically-shaped passwords."""
    feats = features.extract(candidate, delimiters)
    length = feats["length"]
    if length < 4 or length > 40:
        return 0.02
    # Smooth bump centred on a typical human password length.
    score = math.exp(-(((length - 12) / 9.0) ** 2))
    has_lower = feats["n_letters"] > 0 and not candidate.isupper()
    if feats["has_upper"] and has_lower:
        score += 0.15
    if feats["has_digit"]:
        score += 0.10
    if feats["has_special"]:
        score += 0.05
    if feats["ntok"] >= 2:
        score += 0.10
    return max(0.0, min(1.0, score))


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=False))
    na = math.sqrt(sum(x * x for x in a))
    nb = math.sqrt(sum(y * y for y in b))
    return dot / (na * nb) if na and nb else 0.0


class HeuristicRanker:
    """Structural prior, optionally blended with style-seed similarity."""

    def __init__(
        self,
        client: SynapCoresClient | None = None,
        delimiters: Sequence[str] = ("",),
        style_seeds: Sequence[str] | None = None,
    ):
        self.client = client
        self.delimiters = tuple(delimiters)
        self._centroid: list[float] | None = None
        if style_seeds and client is not None:
            self._centroid = self._build_centroid(style_seeds)

    def _build_centroid(self, seeds: Sequence[str]) -> list[float] | None:
        vecs = [self.client.embed(s) for s in seeds if s]
        if not vecs:
            return None
        dim = len(vecs[0])
        return [sum(v[i] for v in vecs) / len(vecs) for i in range(dim)]

    def rank(self, candidates: Sequence[str]) -> Scored:
        scored: Scored = []
        for cand in candidates:
            score = _structural_prior(cand, self.delimiters)
            if self._centroid is not None:
                sim = _cosine(self.client.embed(cand), self._centroid)
                score = 0.5 * score + 0.5 * ((sim + 1.0) / 2.0)
            scored.append((cand, score))
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored


# ---------------------------------------------------------------------------
# AutoML ranker
# ---------------------------------------------------------------------------

_WORDS = [
    "river",
    "shadow",
    "maple",
    "tiger",
    "orange",
    "guitar",
    "silver",
    "rocket",
    "harbor",
    "meadow",
    "cobalt",
    "falcon",
    "ember",
    "willow",
]
_SEP = ["", "-", "_", ".", "!"]


def _synthetic_password(rng: random.Random) -> str:
    parts = rng.sample(_WORDS, rng.randint(1, 3))
    parts = [p.capitalize() if rng.random() < 0.5 else p for p in parts]
    pw = rng.choice(_SEP).join(parts)
    if rng.random() < 0.7:
        pw += str(rng.randint(0, 9999))
    return pw


def _random_string(rng: random.Random) -> str:
    alphabet = "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"
    length = rng.choice([1, 2, 3, rng.randint(28, 48)])
    return "".join(rng.choice(alphabet) for _ in range(length))


class AutoMLRanker:
    """Train an in-DB classifier once, then score candidates by P(password-like)."""

    def __init__(
        self,
        client: SynapCoresClient,
        delimiters: Sequence[str] = ("",),
        n_examples: int = 120,
        time_budget_seconds: int = 40,
        seed: int = 7,
    ):
        self.client = client
        self.delimiters = tuple(delimiters)
        self.n_examples = n_examples
        self.time_budget_seconds = time_budget_seconds
        self.seed = seed
        self.model_id: str | None = None
        self.accuracy: float | None = None
        self._cache: dict = {}

    def train(self) -> dict:
        rng = random.Random(self.seed)
        cols = features.FEATURE_COLUMNS
        self.client.sql(f"DROP TABLE IF EXISTS {RANK_TRAIN_TABLE}")
        coldefs = ", ".join(f"{c} INTEGER" for c in cols)
        self.client.sql(f"CREATE TABLE {RANK_TRAIN_TABLE} ({coldefs}, label INTEGER)")
        rows: list[str] = []
        for _ in range(self.n_examples):
            pw = _synthetic_password(rng)
            rows.append(_row_values(features.vector(pw, self.delimiters), 1))
            rnd = _random_string(rng)
            rows.append(_row_values(features.vector(rnd, self.delimiters), 0))
        # Batch insert for speed.
        collist = ", ".join(cols + ["label"])
        for chunk in _chunks(rows, 50):
            self.client.sql(f"INSERT INTO {RANK_TRAIN_TABLE} ({collist}) VALUES {', '.join(chunk)}")
        dataset_id = self.client.automl_dataset_from_table("sc_rank_ds", RANK_TRAIN_TABLE)
        model = self.client.automl_train(
            dataset_id,
            RANK_TRAIN_TABLE,
            target="label",
            time_budget_seconds=self.time_budget_seconds,
        )
        self.model_id = model.get("id") or model.get("model_id")
        self.accuracy = model.get("accuracy")
        return model

    def rank(self, candidates: Sequence[str]) -> Scored:
        if not self.model_id:
            self.train()
        # Predict once per distinct feature tuple, in a single batched call.
        cand_feats = [(cand, tuple(features.vector(cand, self.delimiters))) for cand in candidates]
        unique = list(dict.fromkeys(f for _, f in cand_feats))
        rows = [dict(zip(features.FEATURE_COLUMNS, f, strict=True)) for f in unique]
        preds = self.client.automl_predict(self.model_id, rows) if rows else []
        score_by_feat = dict(zip(unique, preds, strict=False))
        scored = [(cand, float(score_by_feat.get(f, 0.0))) for cand, f in cand_feats]
        scored.sort(key=lambda p: p[1], reverse=True)
        return scored


def _row_values(feat_values: Sequence[int], label: int) -> str:
    return "(" + ", ".join(str(int(v)) for v in feat_values) + f", {int(label)})"


def _chunks(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
