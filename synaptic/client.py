"""A thin, dependency-free client for the SynapCores CE REST gateway.

Only the standard library is used (``urllib``), so this package adds nothing to
the project's install footprint and its unit tests run anywhere.

The gateway wraps successful responses in ``{"data": ..., "meta": {...}}``; every
method here returns the already-unwrapped ``data``. A handful of endpoint quirks
discovered against v1.6.5.x CE are handled in one place so the rest of the
package can stay clean:

* ``/v1/query/execute`` does not accept ``$1`` placeholders, so SQL values are
  quoted with :func:`sql_literal` instead of bound. All callers in this package
  build SQL through the helpers here; they never interpolate untrusted input.
* vector payloads carry the embedding under ``values`` (not ``vector``).
* the graph endpoints target the tenant's single implicit graph; a ``graph``
  name must be omitted.
* ``/v1/graph/match`` takes its query string under the ``sql`` field (the engine
  accepts Cypher ``MATCH ... RETURN`` there).
* AutoML feature and target columns must be numeric.
"""

from __future__ import annotations

import json
import logging
import time
import urllib.error
import urllib.request
from collections.abc import Sequence
from typing import Any
from urllib.parse import urlparse

from .config import Settings

_log = logging.getLogger("synaptic.client")
_LOCAL_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def _is_local(url: str) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return host in _LOCAL_HOSTS


class SynapCoresError(RuntimeError):
    """Raised when the gateway returns an error or is unreachable."""

    def __init__(
        self,
        message: str,
        status: int | None = None,
        code: str | None = None,
        request_id: str | None = None,
    ):
        super().__init__(message)
        self.status = status
        self.code = code
        self.request_id = request_id


def sql_literal(value: Any) -> str:
    """Render a Python value as a SQL literal for inline interpolation.

    Used because the execute endpoint rejects bound ``$1`` parameters. Strings
    are single-quoted with embedded quotes doubled; ``None`` becomes ``NULL``;
    numbers and bools pass through. This package only ever quotes values it
    generated itself (ids, counts, hex salts, previews), never remote input.
    """
    if value is None:
        return "NULL"
    if isinstance(value, bool):
        return "TRUE" if value else "FALSE"
    if isinstance(value, (int, float)):
        return repr(value)
    text = str(value).replace("'", "''")
    return "'" + text + "'"


class SynapCoresClient:
    """Authenticated access to the SynapCores surfaces this project uses."""

    def __init__(
        self,
        settings: Settings | None = None,
        *,
        timeout: float = 120.0,
        retries: int = 2,
        backoff: float = 0.5,
    ):
        self.settings = settings or Settings.from_env()
        if not _is_local(self.settings.url) and not self.settings.allow_remote:
            raise SynapCoresError(
                f"SYNAPCORES_URL is non-local ({self.settings.url}); synaptic sends "
                "candidate-derived data there. Set SYNAPTIC_ALLOW_REMOTE=1 to permit it."
            )
        self.timeout = timeout
        self.retries = retries
        self.backoff = backoff
        self._token: str | None = self.settings.token
        self.last_request_id: str | None = None

    # -- transport ---------------------------------------------------------

    def _request(
        self,
        method: str,
        path: str,
        body: dict | None = None,
        *,
        auth: bool = True,
        timeout: float | None = None,
    ) -> Any:
        url = self.settings.url + path
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", "Bearer " + self.token())

        # Retry only on connection-level failures (server not reached), so a
        # write is never re-sent after the server may have processed it. HTTP
        # errors mean the server responded and are surfaced immediately.
        attempt = 0
        while True:
            try:
                with urllib.request.urlopen(req, timeout=timeout or self.timeout) as resp:
                    raw = resp.read().decode()
                break
            except urllib.error.HTTPError as exc:
                raise self._http_error(exc) from None
            except urllib.error.URLError as exc:
                if attempt >= self.retries:
                    raise SynapCoresError(
                        f"cannot reach SynapCores at {self.settings.url}: {exc.reason}"
                    ) from None
                delay = self.backoff * (2**attempt)
                _log.warning(
                    "connection to %s failed (%s); retry %d/%d in %.1fs",
                    self.settings.url,
                    exc.reason,
                    attempt + 1,
                    self.retries,
                    delay,
                )
                time.sleep(delay)
                attempt += 1

        if not raw:
            return None
        try:
            payload = json.loads(raw)
        except json.JSONDecodeError:
            return raw
        if isinstance(payload, dict) and isinstance(payload.get("meta"), dict):
            self.last_request_id = payload["meta"].get("request_id")
        if isinstance(payload, dict) and "data" in payload and "meta" in payload:
            return payload["data"]
        return payload

    @staticmethod
    def _http_error(exc: urllib.error.HTTPError) -> SynapCoresError:
        detail = exc.read().decode()[:600]
        code = request_id = None
        try:
            parsed = json.loads(detail)
            err = parsed.get("error", parsed)
            if isinstance(err, dict):
                code = err.get("code")
                detail = err.get("message", detail)
            meta = parsed.get("meta")
            if isinstance(meta, dict):
                request_id = meta.get("request_id")
        except (json.JSONDecodeError, AttributeError):
            pass
        suffix = f" (request_id={request_id})" if request_id else ""
        return SynapCoresError(
            f"HTTP {exc.code}: {detail}{suffix}", status=exc.code, code=code, request_id=request_id
        )

    # -- auth --------------------------------------------------------------

    def token(self) -> str:
        """Return a bearer token, logging in with the admin password if needed."""
        if self._token:
            return self._token
        if not self.settings.password:
            raise SynapCoresError(
                "no SYNAPCORES_TOKEN and no SYNAPCORES_PASSWORD set; cannot authenticate"
            )
        payload = self._request(
            "POST",
            "/v1/auth/login",
            {"username": self.settings.username, "password": self.settings.password},
            auth=False,
        )
        token = payload.get("access_token") if isinstance(payload, dict) else None
        if not token:
            raise SynapCoresError("login succeeded but no access_token was returned")
        self._token = token
        return token

    def health(self) -> dict:
        return self._request("GET", "/health", auth=False)

    # -- sql ---------------------------------------------------------------

    def sql(self, statement: str) -> dict:
        """Execute one SQL statement, returning ``{columns, rows, ...}``."""
        return self._request("POST", "/v1/query/execute", {"sql": statement})

    def sql_rows(self, statement: str) -> list[list]:
        result = self.sql(statement)
        return result.get("rows", []) if isinstance(result, dict) else []

    def sql_scalar(self, statement: str) -> Any:
        rows = self.sql_rows(statement)
        return rows[0][0] if rows and rows[0] else None

    # -- embeddings --------------------------------------------------------

    def embed(self, text: str) -> list[float]:
        """Return the embedding vector for ``text`` (all-MiniLM, 384 dims)."""
        body: dict[str, Any] = {"text": text}
        if self.settings.embed_model:
            body["model"] = self.settings.embed_model
        data = self._request("POST", "/v1/ai/embeddings", body)
        return data["embeddings"]

    def embed_batch(self, texts: Sequence[str]) -> list[list[float]]:
        """Embed many texts in one call (O(1) round-trips instead of O(n))."""
        if not texts:
            return []
        body: dict[str, Any] = {"texts": list(texts)}
        if self.settings.embed_model:
            body["model"] = self.settings.embed_model
        data = self._request("POST", "/v1/ai/embeddings/batch", body)
        return data["embeddings"]

    # -- vectors -----------------------------------------------------------

    def vector_collections(self) -> list[dict]:
        return self._request("GET", "/v1/vectors/collections") or []

    def vector_collection_ensure(
        self, name: str, dimensions: int, distance_metric: str = "cosine"
    ) -> None:
        if any(c.get("name") == name for c in self.vector_collections()):
            return
        try:
            self._request(
                "POST",
                "/v1/vectors/collections",
                {
                    "name": name,
                    "dimensions": dimensions,
                    "distance_metric": distance_metric,
                },
            )
        except SynapCoresError:
            # A concurrent create is fine as long as the collection now exists.
            if not any(c.get("name") == name for c in self.vector_collections()):
                raise

    def vector_add(
        self, collection: str, vector_id: str, values: Sequence[float], metadata: dict | None = None
    ) -> None:
        self._request(
            "POST",
            f"/v1/vectors/collections/{collection}/vectors",
            {"vectors": [{"id": vector_id, "values": list(values), "metadata": metadata or {}}]},
        )

    def vector_add_many(self, collection: str, items: Sequence[dict]) -> None:
        """Add many vectors in one call. Each item: {id, values, metadata?}."""
        if not items:
            return
        vectors = [
            {"id": it["id"], "values": list(it["values"]), "metadata": it.get("metadata", {})}
            for it in items
        ]
        self._request("POST", f"/v1/vectors/collections/{collection}/vectors", {"vectors": vectors})

    def vector_search(
        self, collection: str, values: Sequence[float], k: int = 5, filter: dict | None = None
    ) -> list[dict]:
        body: dict[str, Any] = {"vector": list(values), "k": k}
        if filter:
            body["filter"] = filter
        return self._request("POST", f"/v1/vectors/collections/{collection}/search", body) or []

    # -- graph (implicit tenant graph) -------------------------------------

    def graph_add_node(self, labels: Sequence[str], properties: dict) -> str:
        node = self._request(
            "POST", "/v1/graph/nodes", {"labels": list(labels), "properties": properties}
        )
        return node["id"]

    def graph_add_edge(
        self, src: str, dst: str, edge_type: str, properties: dict | None = None
    ) -> None:
        self._request(
            "POST",
            "/v1/graph/edges",
            {
                "src": src,
                "dst": dst,
                "type": edge_type,
                "properties": properties or {},
            },
        )

    def graph_match(self, cypher: str) -> dict:
        """Run a Cypher ``MATCH ... RETURN`` against the implicit graph."""
        return self._request("POST", "/v1/graph/match", {"sql": cypher})

    # -- automl ------------------------------------------------------------

    def automl_dataset_from_table(
        self, name: str, table: str, dataset_type: str = "classification"
    ) -> str:
        data = self._request(
            "POST",
            "/v1/automl/datasets",
            {
                "name": name,
                "dataset_type": dataset_type,
                "source": {"type": "table", "table": table},
            },
        )
        return data["id"]

    def automl_train(
        self,
        dataset_id: str,
        table: str,
        target: str,
        task: str = "classification",
        time_budget_seconds: int = 40,
    ) -> dict:
        """Train synchronously; returns the model record (id, status, accuracy)."""
        return self._request(
            "POST",
            "/v1/automl/train",
            {
                "dataset_id": dataset_id,
                "task": task,
                "target": target,
                "collection": table,
                "time_budget_seconds": time_budget_seconds,
            },
        )

    def automl_predict(self, model_id: str, rows: list[dict]) -> list[float]:
        """Batch-predict; returns one positive-class score per input row."""
        data = self._request("POST", f"/v1/automl/models/{model_id}/predict", {"inputs": rows})
        preds = data.get("predictions", []) if isinstance(data, dict) else []
        return [float(p) for p in preds]

    # -- llm (optional enhancement) ----------------------------------------

    def extract_entities(self, text: str) -> list[dict]:
        body: dict[str, Any] = {"text": text}
        if self.settings.llm_model:
            body["model"] = self.settings.llm_model
        try:
            data = self._request("POST", "/v1/ai/entities", body, timeout=60)
        except SynapCoresError:
            return []
        return data.get("entities", []) if isinstance(data, dict) else []
