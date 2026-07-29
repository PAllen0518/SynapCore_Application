"""Orchestrator (recover.recover) driven with a fake client - no live database.

Uses btcrecover's real public test wallet so the in-process check genuinely finds
the password, while every SynapCores call is served by an in-memory fake. This
gives CI coverage of the control flow (bootstrap -> graph -> coverage gate -> rank
-> check -> record -> ledger) that previously only ran under SYNAPTIC_LIVE.
"""

import os
import tempfile

import pytest

from synaptic import bitcracker
from synaptic.hints import load_hints
from synaptic.recover import recover

_HINTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "demo_hints.json")


class _FakeClient:
    """In-memory stand-in for SynapCoresClient across the whole recover() path."""

    def __init__(self):
        self.sql_log = []
        self._node = 0

    # SQL
    def sql(self, statement):
        self.sql_log.append(statement)
        return {"columns": [], "rows": []}

    def sql_rows(self, statement):
        return []  # coverage sees no prior candidates -> all new

    def sql_scalar(self, statement):
        return 0  # wallet not yet registered -> insert path

    # vectors / schema
    def vector_collection_ensure(self, *args, **kwargs):
        pass

    def embed(self, text):
        return [0.0] * 384

    # graph
    def graph_match(self, cypher):
        return {"rows": [], "columns": [], "count": 0}  # read-back empty -> use hint_set

    def graph_add_node(self, labels, properties):
        self._node += 1
        return f"node-{self._node}"

    def graph_add_edge(self, src, dst, edge_type, properties=None):
        pass


def _has(log, needle):
    return any(needle in s for s in log)


def test_recover_finds_public_wallet_with_fake_client():
    client = _FakeClient()
    hint_set = load_hints(_HINTS)
    with tempfile.TemporaryDirectory() as d:
        report = recover(
            client, hint_set, bitcracker.DEFAULT_TEST_WALLET, workdir=d, ranker="heuristic"
        )
        assert os.path.exists(os.path.join(d, "RECOVERED_PASSWORD.txt"))
    assert report.found is True
    assert report.found_position is not None
    assert report.num_candidates == 27
    assert report.num_new == 27  # fake client reports nothing tried yet
    assert report.num_skipped == 0
    assert report.checked >= 1


def test_recover_bootstraps_and_records_run():
    client = _FakeClient()
    hint_set = load_hints(_HINTS)
    with tempfile.TemporaryDirectory() as d:
        recover(client, hint_set, bitcracker.DEFAULT_TEST_WALLET, workdir=d, ranker="heuristic")
    assert _has(client.sql_log, "CREATE TABLE IF NOT EXISTS sc_candidates")  # bootstrapped
    assert _has(client.sql_log, "INSERT INTO sc_runs")  # run ledgered
    assert _has(client.sql_log, "INSERT INTO sc_candidates")  # candidates recorded


def test_recover_max_checks_caps_work():
    client = _FakeClient()
    hint_set = load_hints(_HINTS)
    with tempfile.TemporaryDirectory() as d:
        report = recover(
            client,
            hint_set,
            bitcracker.DEFAULT_TEST_WALLET,
            workdir=d,
            ranker="heuristic",
            max_checks=3,
        )
    assert report.checked <= 3


class _FailingClient(_FakeClient):
    """Raises during graph build to exercise the transactional finalize path."""

    def graph_match(self, cypher):
        raise RuntimeError("graph exploded")


def test_recover_finalizes_run_row_on_failure():
    client = _FailingClient()
    hint_set = load_hints(_HINTS)
    with tempfile.TemporaryDirectory() as d, pytest.raises(RuntimeError, match="graph exploded"):
        recover(client, hint_set, bitcracker.DEFAULT_TEST_WALLET, workdir=d, ranker="heuristic")
    # The run was started (INSERT) and finalized (UPDATE ... notes=error) despite the crash.
    assert _has(client.sql_log, "INSERT INTO sc_runs")
    updates = [s for s in client.sql_log if s.strip().upper().startswith("UPDATE SC_RUNS")]
    assert updates and "error:" in updates[-1]
