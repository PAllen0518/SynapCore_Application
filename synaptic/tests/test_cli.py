"""CLI behavior with a fake client (no live database)."""

import os

import pytest

from synaptic import cli
from synaptic.client import SynapCoresError

_HINTS = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "demo_hints.json")


class _FakeCliClient:
    def __init__(self):
        self.settings = type("S", (), {"url": "http://localhost:8090"})()
        self.deleted = []

    def health(self):
        return {"status": "ok"}

    def sql(self, statement):
        if statement.strip().upper().startswith("DELETE"):
            self.deleted.append(statement)
        return {"columns": [], "rows": []}

    def sql_scalar(self, statement):
        return 0

    def sql_rows(self, statement):
        return []

    def vector_collection_ensure(self, *args, **kwargs):
        pass


@pytest.fixture
def fake_client(monkeypatch):
    client = _FakeCliClient()
    monkeypatch.setattr(cli, "_client", lambda: client)
    return client


def test_generate_writes_tokenlist(tmp_path, capsys):
    out = tmp_path / "tokens.txt"
    rc = cli.main(["generate", _HINTS, "--out", str(out)])
    assert rc == 0
    assert out.exists()
    assert "^1^btcr" in out.read_text()
    assert "wrote tokenlist" in capsys.readouterr().out


def test_status_no_label(fake_client, capsys):
    rc = cli.main(["status"])
    assert rc == 0
    assert "wallets registered" in capsys.readouterr().out


def test_status_unknown_label(fake_client, capsys):
    rc = cli.main(["status", "--wallet-label", "nope"])
    assert rc == 0
    assert "no wallet registered" in capsys.readouterr().out


def test_runs_empty(fake_client, capsys):
    rc = cli.main(["runs"])
    assert rc == 0
    assert "no runs recorded yet" in capsys.readouterr().out


def test_forget_unknown_wallet(fake_client, capsys):
    rc = cli.main(["forget", "--wallet-label", "nope"])
    assert rc == 1
    assert "no wallet registered" in capsys.readouterr().out


def test_verbose_flag_sets_logging(fake_client):
    # -vv should not error and should configure debug-level logging.
    import logging

    cli.main(["-vv", "status"])
    assert logging.getLogger("synaptic").getEffectiveLevel() <= logging.DEBUG


def test_synapcores_error_exits_nonzero(monkeypatch):
    def boom():
        raise SynapCoresError("boom")

    monkeypatch.setattr(cli, "_client", boom)
    with pytest.raises(SystemExit):
        cli.main(["status"])


def test_missing_credentials_exits(monkeypatch):
    # _client() should sys.exit when no credentials are configured.
    monkeypatch.setattr(cli.Settings, "from_env", classmethod(lambda cls: cls()))
    with pytest.raises(SystemExit):
        cli.main(["status"])
