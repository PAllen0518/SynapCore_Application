"""Client helpers: SQL literal quoting, settings, envelope unwrap, auth guard."""

import json
import urllib.error

import pytest

from synaptic.client import SynapCoresClient, SynapCoresError, sql_literal
from synaptic.config import Settings


def test_sql_literal_types():
    assert sql_literal(None) == "NULL"
    assert sql_literal(True) == "TRUE"
    assert sql_literal(5) == "5"
    assert sql_literal("plain") == "'plain'"


def test_sql_literal_escapes_single_quotes():
    assert sql_literal("O'Brien") == "'O''Brien'"
    # An injection attempt is neutralised into a quoted literal.
    assert sql_literal("x'); DROP TABLE t;--") == "'x''); DROP TABLE t;--'"


def test_settings_from_env_prefers_token():
    s = Settings.from_env({"SYNAPCORES_URL": "http://h:1/", "SYNAPCORES_TOKEN": "tok"})
    assert s.url == "http://h:1"  # trailing slash trimmed
    assert s.token == "tok"
    assert s.has_credentials()


def test_token_without_credentials_raises():
    client = SynapCoresClient(Settings(url="http://localhost:8090", token=None, password=None))
    with pytest.raises(SynapCoresError):
        client.token()


class _FakeResp:
    def __init__(self, payload):
        self._data = json.dumps(payload).encode()

    def read(self):
        return self._data

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


def test_request_unwraps_data_envelope(monkeypatch):
    client = SynapCoresClient(Settings(url="http://localhost:8090", token="tok"))
    payload = {"data": {"rows": [[1]]}, "meta": {"request_id": "r"}}
    monkeypatch.setattr(
        "synaptic.client.urllib.request.urlopen", lambda req, timeout=None: _FakeResp(payload)
    )
    out = client.sql("SELECT 1")
    assert out == {"rows": [[1]]}  # meta stripped, data returned
    assert client.last_request_id == "r"  # request id captured from meta


def test_request_passes_through_unwrapped_payload(monkeypatch):
    client = SynapCoresClient(Settings(url="http://localhost:8090", token="tok"))
    monkeypatch.setattr(
        "synaptic.client.urllib.request.urlopen",
        lambda req, timeout=None: _FakeResp({"access_token": "abc"}),
    )
    out = client._request("POST", "/v1/auth/login", {}, auth=False)
    assert out == {"access_token": "abc"}


def test_retry_on_connection_error_then_success(monkeypatch):
    client = SynapCoresClient(
        Settings(url="http://localhost:8090", token="tok"), retries=2, backoff=0
    )
    calls = {"n": 0}

    def flaky(req, timeout=None):
        calls["n"] += 1
        if calls["n"] < 3:
            raise urllib.error.URLError("connection refused")
        return _FakeResp({"data": {"ok": 1}, "meta": {}})

    monkeypatch.setattr("synaptic.client.urllib.request.urlopen", flaky)
    monkeypatch.setattr("synaptic.client.time.sleep", lambda _s: None)
    out = client._request("GET", "/health", auth=False)
    assert out == {"ok": 1}
    assert calls["n"] == 3  # two failures, third succeeds


def test_retry_exhausted_raises(monkeypatch):
    client = SynapCoresClient(
        Settings(url="http://localhost:8090", token="tok"), retries=1, backoff=0
    )

    def always_fail(req, timeout=None):
        raise urllib.error.URLError("refused")

    monkeypatch.setattr("synaptic.client.urllib.request.urlopen", always_fail)
    monkeypatch.setattr("synaptic.client.time.sleep", lambda _s: None)
    with pytest.raises(SynapCoresError, match="cannot reach"):
        client._request("GET", "/health", auth=False)
