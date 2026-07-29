"""Idempotent bootstrap of the SynapCores objects synaptic needs.

Three SQL tables and one vector collection hold the persistent "recovery memory".
The graph uses the tenant's implicit graph, so it needs no DDL.

The recovered password is never stored. The candidate table keeps only a salted
SHA-256 (for exact "already tried" checks) plus numeric shape features; the
vector collection keeps only embeddings. The plaintext candidates live only in
the generated tokenlist file, which .gitignore excludes.
"""

from __future__ import annotations

import contextlib

from .client import SynapCoresClient, SynapCoresError

CANDIDATE_VECTORS = "sc_candidate_vectors"
EMBED_DIM = 384

_TABLES = {
    "sc_wallets": """
        CREATE TABLE IF NOT EXISTS sc_wallets (
            id           TEXT PRIMARY KEY,
            label        TEXT,
            wallet_type  TEXT,
            salt_hex     TEXT,
            created_at   TEXT
        )
    """,
    "sc_runs": """
        CREATE TABLE IF NOT EXISTS sc_runs (
            id              TEXT PRIMARY KEY,
            wallet_id       TEXT,
            tokenlist_hash  TEXT,
            num_candidates  INTEGER,
            num_new         INTEGER,
            checked         INTEGER,
            found           INTEGER,
            rate            REAL,
            engine          TEXT,
            started_at      TEXT,
            finished_at     TEXT,
            notes           TEXT
        )
    """,
    # One row per distinct candidate ever considered for a wallet. cand_hash is a
    # salted SHA-256 so coverage checks never need the plaintext. Shape features
    # are numeric so AutoML can train on them directly.
    #
    # cand_hash is a plain column, not a PRIMARY KEY: in CE, DELETE hides rows
    # from queries but does not release their keys from a PK index, so a
    # deleted-then-reinserted key would fail forever. Idempotency is enforced at
    # the application layer (coverage._existing_hashes) instead.
    #
    # A secondary index on wallet_id IS created (see _INDEXES). CE (v1.6.5.x) has
    # a planner bug where, with an index present, a SELECT that projects only a
    # non-filter column fails ("Column 'wallet_id' not found ..."). The workaround
    # is to always include wallet_id in the projection, which the coverage queries
    # do (SELECT wallet_id, cand_hash ...). COUNT(*) is unaffected.
    "sc_candidates": """
        CREATE TABLE IF NOT EXISTS sc_candidates (
            cand_hash   TEXT,
            wallet_id   TEXT,
            length      INTEGER,
            ntok        INTEGER,
            has_digit   INTEGER,
            has_upper   INTEGER,
            has_special INTEGER,
            score       REAL,
            tried       INTEGER,
            first_run   TEXT,
            created_at  TEXT
        )
    """,
}


# Secondary indexes on the wallet-scoped filter columns (CE supports
# CREATE INDEX IF NOT EXISTS). Safe because every coverage/ledger query includes
# wallet_id in its projection, which avoids the CE planner bug noted above. One
# index per table (overlapping indexes on the same table also trip the bug).
_INDEXES = (
    "CREATE INDEX IF NOT EXISTS idx_sc_candidates_wallet ON sc_candidates (wallet_id)",
    "CREATE INDEX IF NOT EXISTS idx_sc_runs_wallet ON sc_runs (wallet_id)",
)


def bootstrap(client: SynapCoresClient) -> None:
    """Create every table, index, and vector collection if not already present."""
    for ddl in _TABLES.values():
        client.sql(" ".join(ddl.split()))
    for index_ddl in _INDEXES:
        client.sql(index_ddl)
    client.vector_collection_ensure(CANDIDATE_VECTORS, EMBED_DIM)


def teardown(client: SynapCoresClient) -> None:
    """Drop everything synaptic created. Used by the demo and integration tests."""
    for table in _TABLES:
        client.sql(f"DROP TABLE IF EXISTS {table}")
    # best-effort: teardown must not fail if the collection is absent
    with contextlib.suppress(SynapCoresError):
        client._request("DELETE", f"/v1/vectors/collections/{CANDIDATE_VECTORS}")
