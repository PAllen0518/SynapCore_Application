"""Coverage hashing and partition logic (with a fake client - no network)."""

from synaptic import coverage


def test_candidate_hash_is_deterministic_and_wallet_scoped():
    a = coverage.candidate_hash("wallet-1", "btcr-test-password")
    assert a == coverage.candidate_hash("wallet-1", "btcr-test-password")
    # Same candidate, different wallet -> different hash.
    assert a != coverage.candidate_hash("wallet-2", "btcr-test-password")
    assert len(a) == 64  # sha-256 hex


class _FakeClient:
    """Minimal stand-in exposing only what coverage.partition needs."""

    def __init__(self, tried_candidates, wallet_id):
        self._tried = {coverage.candidate_hash(wallet_id, c) for c in tried_candidates}

    def sql_rows(self, statement):
        # partition() selects `wallet_id, cand_hash` (the CE indexed-projection
        # workaround), so return two-column rows.
        return [["w", h] for h in self._tried]


def test_partition_splits_new_and_already_tried():
    wallet = "w"
    tried = ["btcr-test-password"]
    client = _FakeClient(tried, wallet)
    candidates = ["btcr-test-password", "btcr-test-Password", "new-one"]
    new, already = coverage.partition(client, wallet, candidates)
    assert already == ["btcr-test-password"]
    assert new == ["btcr-test-Password", "new-one"]


def test_partition_dedupes_within_input():
    client = _FakeClient([], "w")
    new, already = coverage.partition(client, "w", ["dup", "dup", "other"])
    assert new == ["dup", "other"]
    assert already == []


class _ForgetClient:
    """Tracks the DELETEs issued by coverage.forget and serves report counts."""

    def __init__(self):
        self.deletes = []

    def sql(self, statement):
        if statement.strip().upper().startswith("DELETE"):
            self.deletes.append(statement)
        return {"columns": [], "rows": []}

    def sql_scalar(self, statement):
        return 3  # non-zero counts so the "before" snapshot is meaningful


def test_forget_deletes_candidates_and_runs():
    client = _ForgetClient()
    before = coverage.forget(client, "wallet-9")
    assert before == {"candidates_recorded": 3, "candidates_tried": 3, "runs": 3}
    joined = " ".join(client.deletes)
    assert "DELETE FROM sc_candidates" in joined
    assert "DELETE FROM sc_runs" in joined
    # The wallet id is quoted via sql_literal (no raw interpolation).
    assert "'wallet-9'" in joined


class _RecordClient:
    """Serves existing hashes and captures INSERTs for coverage.record."""

    def __init__(self, existing=()):
        self._existing = set(existing)
        self.inserts = []

    def sql_rows(self, statement):
        # _existing_hashes projects (wallet_id, cand_hash); cand_hash at index 1.
        return [["w", h] for h in self._existing]

    def sql(self, statement):
        if statement.strip().upper().startswith("INSERT"):
            self.inserts.append(statement)
        return {"columns": [], "rows": []}


def test_record_skips_existing_and_dedupes_within_batch():
    already = coverage.candidate_hash("w", "aa")
    client = _RecordClient(existing=[already])
    written = coverage.record(
        client, "w", "run-1", [("aa", 0.5), ("bb", 0.9), ("bb", 0.1)], tried=True
    )
    assert written == 1  # aa already recorded; bb inserted once (deduped)
    assert len(client.inserts) == 1
    assert "INSERT INTO sc_candidates" in client.inserts[0]
    assert "'bb'" not in client.inserts[0]  # plaintext is never stored, only the hash
