"""stdio MCP server that exposes the recovery loop as agent tools.

Run it with `python -m synaptic.mcp_server` and point an MCP client at it, e.g.
in claude_desktop_config.json:

    {
      "mcpServers": {
        "synaptic": {
          "command": "python",
          "args": ["-m", "synaptic.mcp_server"],
          "cwd": "/path/to/this/repo",
          "env": {"SYNAPCORES_URL": "http://localhost:8090",
                  "SYNAPCORES_PASSWORD": "..."}
        }
      }
    }

An agent can then run a campaign by chat: check status, ingest hints, generate a
tokenlist, run a recovery step, recall past runs. Transport is newline-delimited
JSON-RPC 2.0 over stdin/stdout, stdlib only.

No tool ever returns the password. A hit reports only that it was found and where
the restricted file went.
"""

from __future__ import annotations

import json
import sys
import tempfile
from typing import Any

from . import coverage, schema
from .client import SynapCoresClient, SynapCoresError
from .config import Settings
from .generate import generate_tokenlist
from .hints import build_graph, load_hints, read_hints_from_graph
from .recover import recent_runs, recover, wallet_id_by_label

PROTOCOL_VERSION = "2024-11-05"
SERVER_INFO = {"name": "synaptic", "version": "0.1.0"}

TOOLS: list[dict[str, Any]] = [
    {
        "name": "sc_status",
        "description": "Report SynapCores health and how much keyspace has been "
        "recorded (optionally for one wallet label).",
        "inputSchema": {
            "type": "object",
            "properties": {"wallet_label": {"type": "string"}},
        },
    },
    {
        "name": "sc_ingest_hints",
        "description": "Load a hint-set JSON file and write it into the property "
        "graph. Returns the ingested hints.",
        "inputSchema": {
            "type": "object",
            "properties": {"hints_path": {"type": "string"}},
            "required": ["hints_path"],
        },
    },
    {
        "name": "sc_generate_tokenlist",
        "description": "Generate a btcrecover-style tokenlist from a hint-set file "
        "and return it as text.",
        "inputSchema": {
            "type": "object",
            "properties": {"hints_path": {"type": "string"}},
            "required": ["hints_path"],
        },
    },
    {
        "name": "sc_run_recovery",
        "description": "Run one recovery step: ingest hints, generate + rank "
        "candidates, skip already-tried ones, and check the rest in "
        "order. Reports whether the password was found (never the "
        "password itself).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "hints_path": {"type": "string"},
                "wallet_path": {"type": "string"},
                "ranker": {"type": "string", "enum": ["heuristic", "automl", "auto"]},
                "max_checks": {"type": "integer"},
            },
            "required": ["hints_path", "wallet_path"],
        },
    },
    {
        "name": "sc_coverage_report",
        "description": "Summarise how many candidates have been recorded/tried for a wallet label.",
        "inputSchema": {
            "type": "object",
            "properties": {"wallet_label": {"type": "string"}},
            "required": ["wallet_label"],
        },
    },
    {
        "name": "sc_recall_runs",
        "description": "Recall recent recovery runs (most recent first).",
        "inputSchema": {
            "type": "object",
            "properties": {
                "wallet_label": {"type": "string"},
                "limit": {"type": "integer"},
            },
        },
    },
]


class ToolError(RuntimeError):
    pass


def _client() -> SynapCoresClient:
    settings = Settings.from_env()
    if not settings.has_credentials():
        raise ToolError("no SYNAPCORES_TOKEN or SYNAPCORES_PASSWORD in the server env")
    return SynapCoresClient(settings)


# -- tool implementations ---------------------------------------------------


def _tool_status(args: dict) -> str:
    client = _client()
    health = client.health()
    schema.bootstrap(client)
    out = {"url": client.settings.url, "health": health.get("status")}
    label = args.get("wallet_label")
    if label:
        wid = wallet_id_by_label(client, label)
        out["wallet"] = coverage.coverage_report(client, wid) if wid else "not registered"
    else:
        out["wallets"] = client.sql_scalar("SELECT COUNT(*) FROM sc_wallets") or 0
        out["runs"] = client.sql_scalar("SELECT COUNT(*) FROM sc_runs") or 0
    return json.dumps(out, indent=2)


def _tool_ingest(args: dict) -> str:
    client = _client()
    schema.bootstrap(client)
    hint_set = load_hints(args["hints_path"])
    build_graph(client, hint_set)
    hints = read_hints_from_graph(client, hint_set.wallet_label)
    return json.dumps(
        {
            "wallet_label": hint_set.wallet_label,
            "delimiters": hint_set.delimiters,
            "hints": [
                {"text": h.text, "kind": h.kind, "weight": h.weight, "required": h.required}
                for h in hints
            ],
        },
        indent=2,
    )


def _tool_generate(args: dict) -> str:
    hint_set = load_hints(args["hints_path"])
    return generate_tokenlist(
        hint_set.hints,
        hint_set.delimiters,
        header=f"generated by synaptic for {hint_set.wallet_label}",
    )


def _tool_run_recovery(args: dict) -> str:
    client = _client()
    hint_set = load_hints(args["hints_path"])
    workdir = tempfile.mkdtemp(prefix="synaptic_mcp_")
    report = recover(
        client,
        hint_set,
        args["wallet_path"],
        workdir=workdir,
        ranker=args.get("ranker", "heuristic"),
        max_checks=args.get("max_checks"),
    )
    return json.dumps(report.as_dict(), indent=2)


def _tool_coverage(args: dict) -> str:
    client = _client()
    schema.bootstrap(client)
    wid = wallet_id_by_label(client, args["wallet_label"])
    if not wid:
        return json.dumps({"error": "wallet label not registered"})
    return json.dumps(coverage.coverage_report(client, wid), indent=2)


_RECALL_DEFAULT_LIMIT = 10
_RECALL_MAX_LIMIT = 100


def _tool_recall(args: dict) -> str:
    client = _client()
    schema.bootstrap(client)
    # Bound the page size so a large history can't return unboundedly.
    limit = args.get("limit", _RECALL_DEFAULT_LIMIT)
    limit = max(1, min(int(limit), _RECALL_MAX_LIMIT))
    rows = recent_runs(client, args.get("wallet_label"), limit=limit)
    return json.dumps({"limit": limit, "count": len(rows), "runs": rows}, indent=2, default=str)


_SCHEMA_BY_TOOL = {t["name"]: t["inputSchema"] for t in TOOLS}

_JSON_TYPES: dict[str, type | tuple[type, ...]] = {
    "string": str,
    "integer": int,
    "number": (int, float),
    "boolean": bool,
    "object": dict,
    "array": list,
}


def _validate_args(name: str, args: dict) -> str | None:
    """Return an error string if args violate the tool's inputSchema, else None."""
    schema_def = _SCHEMA_BY_TOOL.get(name, {})
    props = schema_def.get("properties", {})
    for req in schema_def.get("required", []):
        if req not in args:
            return f"missing required argument: {req}"
    for key, value in args.items():
        spec = props.get(key)
        if not spec or "type" not in spec:
            continue
        expected = _JSON_TYPES.get(spec["type"])
        # bool is an int subclass; reject it where a plain integer is expected.
        if spec["type"] == "integer" and isinstance(value, bool):
            return f"argument {key} must be an integer"
        if expected and not isinstance(value, expected):
            return f"argument {key} must be of type {spec['type']}"
    return None


_DISPATCH = {
    "sc_status": _tool_status,
    "sc_ingest_hints": _tool_ingest,
    "sc_generate_tokenlist": _tool_generate,
    "sc_run_recovery": _tool_run_recovery,
    "sc_coverage_report": _tool_coverage,
    "sc_recall_runs": _tool_recall,
}


# -- JSON-RPC plumbing ------------------------------------------------------


def handle_message(msg: dict) -> dict | None:
    """Handle one JSON-RPC request; return a response, or None for notifications."""
    method = msg.get("method")
    msg_id = msg.get("id")
    if method == "initialize":
        return _result(
            msg_id,
            {
                "protocolVersion": PROTOCOL_VERSION,
                "capabilities": {"tools": {}},
                "serverInfo": SERVER_INFO,
            },
        )
    if method == "notifications/initialized":
        return None
    if method == "ping":
        return _result(msg_id, {})
    if method == "tools/list":
        return _result(msg_id, {"tools": TOOLS})
    if method == "tools/call":
        params = msg.get("params", {})
        name = params.get("name")
        args = params.get("arguments", {}) or {}
        impl = _DISPATCH.get(name)
        if impl is None:
            return _error(msg_id, -32601, f"unknown tool: {name}")
        validation_error = _validate_args(name, args)
        if validation_error is not None:
            return _result(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"error: {validation_error}"}],
                    "isError": True,
                },
            )
        try:
            text = impl(args)
            return _result(msg_id, {"content": [{"type": "text", "text": text}]})
        except (ToolError, SynapCoresError, FileNotFoundError, KeyError) as exc:
            return _result(
                msg_id,
                {
                    "content": [{"type": "text", "text": f"error: {exc}"}],
                    "isError": True,
                },
            )
    if msg_id is not None:
        return _error(msg_id, -32601, f"unknown method: {method}")
    return None


def _result(msg_id: Any, result: dict) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "result": result}


def _error(msg_id: Any, code: int, message: str) -> dict:
    return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": code, "message": message}}


def serve(stdin=None, stdout=None) -> None:
    """Read newline-delimited JSON-RPC from stdin, write responses to stdout."""
    stdin = stdin or sys.stdin
    stdout = stdout or sys.stdout
    for line in stdin:
        line = line.strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except json.JSONDecodeError:
            continue
        response = handle_message(msg)
        if response is not None:
            stdout.write(json.dumps(response) + "\n")
            stdout.flush()


if __name__ == "__main__":
    serve()
