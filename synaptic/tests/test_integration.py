"""Opt-in end-to-end test against a live SynapCores instance.

Skipped unless SYNAPTIC_LIVE=1 and credentials are in the environment, so CI
(which has no database) stays green. When enabled it drives the full loop and
asserts the public test wallet's password is recovered.
"""

import os
import tempfile

import pytest

LIVE = os.environ.get("SYNAPTIC_LIVE") == "1"

pytestmark = pytest.mark.skipif(
    not LIVE, reason="set SYNAPTIC_LIVE=1 (and SYNAPCORES_* creds) to run"
)


def _client():
    from synaptic import SynapCoresClient
    from synaptic.config import Settings

    settings = Settings.from_env()
    if not settings.has_credentials():
        pytest.skip("no SYNAPCORES_TOKEN/PASSWORD in environment")
    return SynapCoresClient(settings)


def test_full_recovery_finds_public_test_wallet():
    from synaptic import bitcracker, schema
    from synaptic.hints import load_hints
    from synaptic.recover import recover

    client = _client()
    for table in ("sc_candidates", "sc_runs", "sc_wallets"):
        client.sql(f"DROP TABLE IF EXISTS {table}")
    schema.bootstrap(client)

    hints_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "examples", "demo_hints.json"
    )
    hint_set = load_hints(hints_path)
    with tempfile.TemporaryDirectory() as d:
        report = recover(
            client, hint_set, bitcracker.DEFAULT_TEST_WALLET, workdir=d, ranker="heuristic"
        )
    assert report.found is True
    assert report.found_position is not None


def test_coverage_skips_on_second_run():
    from synaptic import bitcracker, schema
    from synaptic.hints import load_hints
    from synaptic.recover import recover

    client = _client()
    for table in ("sc_candidates", "sc_runs", "sc_wallets"):
        client.sql(f"DROP TABLE IF EXISTS {table}")
    schema.bootstrap(client)
    hints_path = os.path.join(
        os.path.dirname(os.path.dirname(__file__)), "examples", "demo_hints.json"
    )
    hint_set = load_hints(hints_path)
    with tempfile.TemporaryDirectory() as d:
        first = recover(
            client,
            hint_set,
            bitcracker.DEFAULT_TEST_WALLET,
            workdir=d,
            ranker="heuristic",
            max_checks=5,
        )
        second = recover(
            client, hint_set, bitcracker.DEFAULT_TEST_WALLET, workdir=d, ranker="heuristic"
        )
    assert first.checked == 5
    assert second.num_skipped >= 5  # round 1's checks are now covered
