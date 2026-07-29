"""Ranking logic — heuristic ordering (pure) and AutoML score-mapping (fake client)."""

from synaptic.rank import AutoMLRanker, HeuristicRanker


def test_heuristic_orders_realistic_above_junk():
    ranker = HeuristicRanker(delimiters=["-"])
    cands = ["ab", "btcr-test-password", "x" * 45]
    ranked = ranker.rank(cands)
    order = [c for c, _ in ranked]
    # A realistic multi-word candidate beats a 2-char and a 45-char junk string.
    assert order[0] == "btcr-test-password"
    assert order[-1] in {"ab", "x" * 45}


def test_heuristic_is_sorted_descending_and_total():
    ranker = HeuristicRanker(delimiters=[""])
    cands = ["alpha", "Alpha1", "alphabravocharlie", "q"]
    ranked = ranker.rank(cands)
    scores = [s for _, s in ranked]
    assert scores == sorted(scores, reverse=True)
    assert {c for c, _ in ranked} == set(cands)  # nothing dropped


class _FakeAutoMLClient:
    """Stands in for SynapCoresClient across the AutoMLRanker train+predict path."""

    def __init__(self):
        self.trained = False

    def sql(self, statement):
        return {"columns": [], "rows": []}

    def automl_dataset_from_table(self, name, table, dataset_type="classification"):
        return "ds-1"

    def automl_train(
        self, dataset_id, table, target, task="classification", time_budget_seconds=40
    ):
        self.trained = True
        return {"id": "model-1", "accuracy": 1.0}

    def automl_predict(self, model_id, rows):
        # Score peaks at length 12 so ordering is deterministic and assertable.
        return [1.0 / (1 + abs(r["length"] - 12)) for r in rows]


def test_automl_trains_and_maps_predictions_to_candidates():
    client = _FakeAutoMLClient()
    ranker = AutoMLRanker(client, delimiters=[""])
    cands = ["ab", "abcdefghijkl", "abcdefghijklmnopqrstuvwxyz"]  # len 2, 12, 26
    ranked = ranker.rank(cands)
    assert client.trained
    assert ranker.model_id == "model-1"
    assert ranker.accuracy == 1.0
    # The length-12 candidate scores highest under the fake model.
    assert ranked[0][0] == "abcdefghijkl"
    assert {c for c, _ in ranked} == set(cands)
    assert [s for _, s in ranked] == sorted((s for _, s in ranked), reverse=True)


def test_automl_reuses_trained_model():
    client = _FakeAutoMLClient()
    ranker = AutoMLRanker(client, delimiters=[""])
    ranker.rank(["abcd"])
    client.trained = False
    ranker.rank(["efgh"])  # model_id already set -> must not retrain
    assert client.trained is False
