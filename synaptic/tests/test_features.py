"""Numeric feature extraction."""

from synaptic import features


def test_feature_columns_all_present_and_int():
    feats = features.extract("Btcr-Test-1", delimiters=["-"])
    assert set(feats) == set(features.FEATURE_COLUMNS)
    assert all(isinstance(v, int) for v in feats.values())


def test_shape_flags():
    feats = features.extract("abc-DEF-9!", delimiters=["-"])
    assert feats["has_digit"] == 1
    assert feats["has_upper"] == 1
    assert feats["has_special"] == 1  # '!'
    assert feats["length"] == 10


def test_segment_count_by_delimiter():
    assert features.extract("a-b-c", delimiters=["-"])["ntok"] == 3
    assert features.extract("abc", delimiters=["-"])["ntok"] == 1
    assert features.extract("abc", delimiters=[""])["ntok"] == 1


def test_vector_matches_column_order():
    vec = features.vector("btcr-test-password", delimiters=["-"])
    feats = features.extract("btcr-test-password", delimiters=["-"])
    assert vec == [feats[c] for c in features.FEATURE_COLUMNS]
    assert vec[0] == len("btcr-test-password")
