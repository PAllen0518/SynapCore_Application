"""Client method request-shapes and response-parsing, with _request stubbed."""

from synaptic.client import SynapCoresClient
from synaptic.config import Settings


class _Recorder:
    """Captures (method, path, body) and returns canned responses per path."""

    def __init__(self, responses):
        self.calls = []
        self._responses = responses

    def __call__(self, method, path, body=None, **kwargs):
        self.calls.append((method, path, body))
        for key, value in self._responses.items():
            if key in path:
                return value
        return {}


def _client(responses):
    c = SynapCoresClient(Settings(url="http://localhost:8090", token="tok"))
    rec = _Recorder(responses)
    c._request = rec  # type: ignore[assignment]
    return c, rec


def test_embed_and_batch():
    c, rec = _client(
        {
            "/v1/ai/embeddings/batch": {"embeddings": [[0.1] * 384, [0.2] * 384]},
            "/v1/ai/embeddings": {"embeddings": [0.1] * 384},
        }
    )
    assert len(c.embed("hi")) == 384
    assert len(c.embed_batch(["a", "b"])) == 2
    assert c.embed_batch([]) == []  # short-circuits, no call
    paths = [p for _, p, _ in rec.calls]
    assert "/v1/ai/embeddings" in paths[0]


def test_embed_pins_model_when_configured():
    c = SynapCoresClient(
        Settings(url="http://localhost:8090", token="tok", embed_model="all-minilm")
    )
    rec = _Recorder({"/v1/ai/embeddings": {"embeddings": [0.0] * 384}})
    c._request = rec  # type: ignore[assignment]
    c.embed("hi")
    _, _, body = rec.calls[0]
    assert body["model"] == "all-minilm"


def test_vector_add_and_add_many_shapes():
    c, rec = _client({"/vectors": None})
    c.vector_add("col", "id1", [0.1, 0.2], {"k": "v"})
    c.vector_add_many("col", [{"id": "a", "values": [0.1]}, {"id": "b", "values": [0.2]}])
    c.vector_add_many("col", [])  # no-op, no call
    add_body = rec.calls[0][2]
    assert add_body["vectors"][0]["values"] == [0.1, 0.2]
    many_body = rec.calls[1][2]
    assert [v["id"] for v in many_body["vectors"]] == ["a", "b"]
    assert len(rec.calls) == 2  # empty add_many made no request


def test_vector_collection_ensure_skips_when_present():
    c, rec = _client({"/v1/vectors/collections": [{"name": "col"}]})
    c.vector_collection_ensure("col", 384)
    # Only the list GET happened; no POST create, since the collection exists.
    assert all(m == "GET" for m, _, _ in rec.calls)


def test_graph_helpers():
    c, rec = _client(
        {
            "/v1/graph/nodes": {"id": "n1"},
            "/v1/graph/edges": None,
            "/v1/graph/match": {"rows": [[{"id": "n1"}]], "count": 1},
        }
    )
    assert c.graph_add_node(["Hint"], {"text": "x"}) == "n1"
    c.graph_add_edge("n1", "n2", "REMEMBERS", {"weight": 3})
    assert c.graph_match("MATCH (n) RETURN n")["count"] == 1
    edge_body = next(b for _, p, b in rec.calls if "edges" in p)
    assert (
        edge_body["src"] == "n1" and edge_body["dst"] == "n2" and edge_body["type"] == "REMEMBERS"
    )
    match_body = next(b for _, p, b in rec.calls if "match" in p)
    assert "sql" in match_body  # Cypher goes under the `sql` field


def test_automl_train_and_predict():
    c, rec = _client(
        {
            "/v1/automl/datasets": {"id": "ds1"},
            "/v1/automl/train": {"id": "m1", "accuracy": 1.0},
            "/predict": {"predictions": [0.9, 0.1]},
        }
    )
    ds = c.automl_dataset_from_table("ds", "tbl")
    assert ds == "ds1"
    model = c.automl_train(ds, "tbl", target="label")
    assert model["id"] == "m1"
    preds = c.automl_predict("m1", [{"length": 5}, {"length": 2}])
    assert preds == [0.9, 0.1]
    predict_body = next(b for _, p, b in rec.calls if "predict" in p)
    assert "inputs" in predict_body


def test_sql_helpers_parse_rows():
    c, rec = _client({"/v1/query/execute": {"columns": [], "rows": [[7]]}})
    assert c.sql_rows("SELECT 1") == [[7]]
    assert c.sql_scalar("SELECT 1") == 7


def test_extract_entities_returns_list():
    c, rec = _client({"/v1/ai/entities": {"entities": [{"text": "Rex", "type": "person"}]}})
    ents = c.extract_entities("my dog Rex")
    assert ents[0]["text"] == "Rex"
