"""Coverage tracking, so we never sweep the same keyspace twice.

Each candidate a wallet has been searched with is stored as a salted SHA-256 in
sc_candidates (the plaintext is never stored), and optionally as an embedding in
sc_candidate_vectors for near-duplicate reporting. partition() splits a fresh
candidate list into already-tried and new, across sessions, not just within one
run.
"""

from __future__ import annotations

import hashlib
import os
from collections.abc import Sequence

from . import features, schema
from .client import SynapCoresClient, sql_literal

# Application salt. This is not a secret - the operator owns these candidates -
# it just keeps stored hashes from being trivially reversible via a rainbow table
# and scopes them to this tool. Override per-install via SYNAPTIC_SALT for defense
# in depth.
_APP_SALT = os.environ.get("SYNAPTIC_SALT", "synaptic-coverage-v1").encode("utf-8")


def candidate_hash(wallet_id: str, candidate: str) -> str:
    h = hashlib.sha256()
    h.update(_APP_SALT)
    h.update(wallet_id.encode("utf-8"))
    h.update(b"\x00")
    h.update(candidate.encode("utf-8", "surrogatepass"))
    return h.hexdigest()


def _tried_hashes(client: SynapCoresClient, wallet_id: str) -> set:
    # With an index present, CE requires every column referenced in the WHERE to
    # also appear in the projection (see schema.py). So project wallet_id + tried
    # (both filtered on) alongside cand_hash, which is at index 1.
    rows = client.sql_rows(
        f"SELECT wallet_id, cand_hash, tried FROM sc_candidates "
        f"WHERE wallet_id = {sql_literal(wallet_id)} AND tried = 1"
    )
    return {r[1] for r in rows}


def partition(
    client: SynapCoresClient, wallet_id: str, candidates: Sequence[str]
) -> tuple[list[str], list[str]]:
    """Split candidates into (new, already_tried), preserving input order."""
    tried = _tried_hashes(client, wallet_id)
    new: list[str] = []
    seen_now: set = set()
    already: list[str] = []
    for cand in candidates:
        digest = candidate_hash(wallet_id, cand)
        if digest in tried:
            already.append(cand)
        elif digest not in seen_now:
            seen_now.add(digest)
            new.append(cand)
    return new, already


def semantic_duplicates(
    client: SynapCoresClient, candidates: Sequence[str], threshold: float = 0.97, k: int = 3
) -> list[dict]:
    """Report candidates that are embedding-near an already-recorded one.

    Advisory only: this flags likely redundant variants (for the operator to
    prune) but does not remove anything, because embedding similarity on short
    password-like strings is noisy.
    """
    hits: list[dict] = []
    vecs = client.embed_batch(list(candidates))
    for cand, vec in zip(candidates, vecs, strict=False):
        matches = client.vector_search(schema.CANDIDATE_VECTORS, vec, k=k)
        near = [m for m in matches if m.get("score", 0.0) >= threshold]
        if near:
            hits.append({"candidate": cand, "matches": near})
    return hits


def record(
    client: SynapCoresClient,
    wallet_id: str,
    run_id: str,
    scored: Sequence[tuple[str, float]],
    delimiters: Sequence[str] = ("",),
    tried: bool = True,
    embed: bool = False,
) -> int:
    """Persist candidates (as hashes + numeric features + score) for a run.

    Idempotent on the candidate hash: rows already recorded for this wallet are
    skipped rather than upserted (the engine's ON CONFLICT update cannot
    reference the existing row). With embed=True each new candidate's
    embedding is also written to the vector collection for later
    semantic-duplicate reporting. Returns the number of new rows written.
    """
    from datetime import datetime, timezone

    now = datetime.now(timezone.utc).isoformat()
    existing = _existing_hashes(client, wallet_id)
    values: list[str] = []
    seen: set = set()
    to_embed: list[tuple[str, str]] = []  # (digest, candidate) for the embed path
    for cand, score in scored:
        digest = candidate_hash(wallet_id, cand)
        if digest in existing or digest in seen:
            continue
        seen.add(digest)
        f = features.extract(cand, delimiters)
        values.append(
            "("
            + ", ".join(
                [
                    sql_literal(digest),
                    sql_literal(wallet_id),
                    str(f["length"]),
                    str(f["ntok"]),
                    str(f["has_digit"]),
                    str(f["has_upper"]),
                    str(f["has_special"]),
                    repr(float(score)),
                    "1" if tried else "0",
                    sql_literal(run_id),
                    sql_literal(now),
                ]
            )
            + ")"
        )
        if embed:
            to_embed.append((digest, cand))
    if to_embed:
        # One batched embedding call + one bulk vector insert, instead of O(n).
        vecs = client.embed_batch([c for _, c in to_embed])
        client.vector_add_many(
            schema.CANDIDATE_VECTORS,
            [
                {
                    "id": digest,
                    "values": vec,
                    "metadata": {"wallet_id": wallet_id, "run_id": run_id},
                }
                for (digest, _), vec in zip(to_embed, vecs, strict=False)
            ],
        )
    written = 0
    cols = (
        "cand_hash, wallet_id, length, ntok, has_digit, has_upper, "
        "has_special, score, tried, first_run, created_at"
    )
    for chunk in _chunks(values, 50):
        client.sql(f"INSERT INTO sc_candidates ({cols}) VALUES {', '.join(chunk)}")
        written += len(chunk)
    return written


def _existing_hashes(client: SynapCoresClient, wallet_id: str) -> set:
    # wallet_id first in the projection (CE indexed-projection workaround).
    rows = client.sql_rows(
        f"SELECT wallet_id, cand_hash FROM sc_candidates WHERE wallet_id = {sql_literal(wallet_id)}"
    )
    return {r[1] for r in rows}


def forget(client: SynapCoresClient, wallet_id: str) -> dict[str, int]:
    """Delete all stored coverage and run history for a wallet.

    A retention/privacy control: removes the salted-hash coverage rows and run
    ledger entries for one wallet (the wallet registration itself is kept).
    Returns the counts that were present before deletion.
    """
    before = coverage_report(client, wallet_id)
    wid = sql_literal(wallet_id)
    client.sql(f"DELETE FROM sc_candidates WHERE wallet_id = {wid}")
    client.sql(f"DELETE FROM sc_runs WHERE wallet_id = {wid}")
    return before


def coverage_report(client: SynapCoresClient, wallet_id: str) -> dict[str, int]:
    """Summary counts of how much keyspace has been recorded for a wallet."""
    wid = sql_literal(wallet_id)
    total = client.sql_scalar(f"SELECT COUNT(*) FROM sc_candidates WHERE wallet_id = {wid}") or 0
    tried = (
        client.sql_scalar(
            f"SELECT COUNT(*) FROM sc_candidates WHERE wallet_id = {wid} AND tried = 1"
        )
        or 0
    )
    runs = client.sql_scalar(f"SELECT COUNT(*) FROM sc_runs WHERE wallet_id = {wid}") or 0
    return {"candidates_recorded": int(total), "candidates_tried": int(tried), "runs": int(runs)}


def _chunks(seq: list[str], size: int):
    for i in range(0, len(seq), size):
        yield seq[i : i + size]
