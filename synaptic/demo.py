"""Reproducible end-to-end demo against btcrecover's public test wallet.

Run it (with a SynapCores instance up and creds in the environment)::

    python -m synaptic.demo

The wallet is ``multibit-wallet.key`` - btcrecover's public test fixture, whose
password ``btcr-test-password`` is documented and which holds no funds - so this
is a safe, deterministic showcase of every SynapCores surface:

  graph  -> hints go into the property graph and are read back (GraphRAG)
  automl -> an in-database classifier ranks the candidates
  sql    -> a run ledger tracks coverage so work is never repeated
  vector -> candidate embeddings back semantic-duplicate reporting

Narrative: round 1 spends a small budget with the heuristic ranker and records
what it tried; round 2 switches to the AutoML ranker, skips everything round 1
already covered, and finds the password among the rest.
"""

from __future__ import annotations

import os
import sys
import tempfile

from . import bitcracker, coverage, schema
from .client import SynapCoresClient
from .config import Settings
from .hints import build_graph, load_hints, read_hints_from_graph
from .recover import recent_runs, recover

_HINTS = os.path.join(os.path.dirname(__file__), "examples", "demo_hints.json")


def _rule(title: str) -> None:
    print("\n" + title)
    print("-" * len(title))


def main() -> int:
    settings = Settings.from_env()
    if not settings.has_credentials():
        sys.exit("Set SYNAPCORES_TOKEN or SYNAPCORES_PASSWORD first (see synaptic/README.md).")
    client = SynapCoresClient(settings)

    print("== synaptic x SynapCores CE - reproducible recovery demo ==")
    print(f"SynapCores: {client.settings.url}  ({client.health().get('status')})")
    wallet_path = bitcracker.DEFAULT_TEST_WALLET
    print(f"wallet    : {os.path.relpath(wallet_path)}")

    # Clean slate. DROP (not DELETE) so the primary-key indexes are truly reset.
    for table in ("sc_candidates", "sc_runs", "sc_wallets"):
        client.sql(f"DROP TABLE IF EXISTS {table}")
    schema.bootstrap(client)

    hint_set = load_hints(_HINTS)

    _rule("1. Hints -> property graph (GraphRAG source of truth)")
    build_graph(client, hint_set)
    for hint in read_hints_from_graph(client, hint_set.wallet_label):
        flag = "required" if hint.required else "optional"
        print(f"   ({flag}) w={hint.weight} {hint.text!r}")

    workdir = tempfile.mkdtemp(prefix="synaptic_demo_")

    _rule("2. Round 1 - heuristic ranker, small budget (records what it tries)")
    r1 = recover(client, hint_set, wallet_path, workdir=workdir, ranker="heuristic", max_checks=8)
    print(
        f"   candidates={r1.num_candidates} new={r1.num_new} checked={r1.checked} found={r1.found}"
    )
    print(f"   coverage now: {coverage.coverage_report(client, r1.wallet_id)}")

    _rule("3. Round 2 - AutoML ranker, skips round 1's coverage")
    r2 = recover(client, hint_set, wallet_path, workdir=workdir, ranker="automl")
    print(
        f"   candidates={r2.num_candidates} skipped_already_tried={r2.num_skipped} new={r2.num_new}"
    )
    if r2.accuracy is not None:
        print(f"   in-database model accuracy: {r2.accuracy}")
    if r2.found:
        print(f"   FOUND at ranked position {r2.found_position} after {r2.checked} checks")
        print("   password written to RECOVERED_PASSWORD.txt (not shown, not stored)")
    else:
        print(f"   not found; checked {r2.checked}")

    _rule("4. Run ledger (SQL)")
    for run in recent_runs(client, hint_set.wallet_label):
        print(
            f"   run {run['id'][:8]} checked={run['checked']} "
            f"new={run['num_new']} found={run['found']}"
        )

    found = r1.found or r2.found
    print(
        "\n== demo complete:", "password recovered" if found else "NOT recovered (unexpected)", "=="
    )
    return 0 if found else 1


if __name__ == "__main__":
    raise SystemExit(main())
