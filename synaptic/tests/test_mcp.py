"""MCP JSON-RPC protocol handling (the DB-free methods)."""

import json

import pytest

from synaptic import mcp_server


def test_initialize_returns_protocol_and_server_info():
    resp = mcp_server.handle_message(
        {"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
    )
    assert resp["id"] == 1
    assert resp["result"]["protocolVersion"] == mcp_server.PROTOCOL_VERSION
    assert resp["result"]["serverInfo"]["name"] == "synaptic"
    assert "tools" in resp["result"]["capabilities"]


def test_initialized_notification_has_no_response():
    assert (
        mcp_server.handle_message({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    )


def test_tools_list_exposes_recovery_tools():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    names = {t["name"] for t in resp["result"]["tools"]}
    assert {"sc_status", "sc_run_recovery", "sc_recall_runs"} <= names
    for tool in resp["result"]["tools"]:
        assert tool["inputSchema"]["type"] == "object"


def test_generate_tool_needs_no_database():
    import os

    hints = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "demo_hints.json")
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 3,
            "method": "tools/call",
            "params": {"name": "sc_generate_tokenlist", "arguments": {"hints_path": hints}},
        }
    )
    text = resp["result"]["content"][0]["text"]
    assert "^1^btcr" in text


def test_unknown_tool_reports_error():
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "does_not_exist", "arguments": {}},
        }
    )
    assert resp["error"]["code"] == -32601


def test_ping():
    resp = mcp_server.handle_message({"jsonrpc": "2.0", "id": 5, "method": "ping"})
    assert resp["result"] == {}


def test_validation_missing_required_argument():
    # sc_ingest_hints requires hints_path; omitting it is caught before dispatch.
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 6,
            "method": "tools/call",
            "params": {"name": "sc_ingest_hints", "arguments": {}},
        }
    )
    assert resp["result"]["isError"] is True
    assert "missing required" in resp["result"]["content"][0]["text"]


def test_validation_wrong_argument_type():
    resp = mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 7,
            "method": "tools/call",
            "params": {
                "name": "sc_run_recovery",
                "arguments": {"hints_path": "h", "wallet_path": "w", "max_checks": "lots"},
            },
        }
    )
    assert resp["result"]["isError"] is True
    assert "max_checks" in resp["result"]["content"][0]["text"]


def test_recall_limit_is_bounded():
    assert mcp_server._RECALL_MAX_LIMIT == 100
    # The clamp logic itself (no DB needed).
    assert max(1, min(9999, mcp_server._RECALL_MAX_LIMIT)) == 100
    assert max(1, min(0, mcp_server._RECALL_MAX_LIMIT)) == 1


class _FakeMcpClient:
    settings = type("S", (), {"url": "http://localhost:8090"})()

    def health(self):
        return {"status": "ok"}

    def sql(self, statement):
        return {"columns": [], "rows": []}

    def sql_scalar(self, statement):
        return 0

    def sql_rows(self, statement):
        return []

    def vector_collection_ensure(self, *args, **kwargs):
        pass


@pytest.fixture
def fake_mcp(monkeypatch):
    monkeypatch.setattr(mcp_server, "_client", lambda: _FakeMcpClient())


def _call(name, args):
    return mcp_server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 9,
            "method": "tools/call",
            "params": {"name": name, "arguments": args},
        }
    )


def test_status_tool_dispatch(fake_mcp):
    resp = _call("sc_status", {})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["health"] == "ok"
    assert "wallets" in body


def test_recall_tool_returns_bounded_envelope(fake_mcp):
    resp = _call("sc_recall_runs", {"limit": 9999})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert body["limit"] == mcp_server._RECALL_MAX_LIMIT  # clamped
    assert body["runs"] == []


def test_coverage_tool_unregistered_wallet(fake_mcp):
    resp = _call("sc_coverage_report", {"wallet_label": "nope"})
    body = json.loads(resp["result"]["content"][0]["text"])
    assert "error" in body
