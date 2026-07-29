"""Hint parsing, the example file, and deterministic free-text enrichment."""

import os

from synaptic.hints import (
    REQUIRED_WEIGHT,
    HintSet,
    enrich_freeform,
    load_hints,
)

_EXAMPLE = os.path.join(os.path.dirname(os.path.dirname(__file__)), "examples", "demo_hints.json")


def test_from_dict_reads_hints_and_delimiters():
    hs = HintSet.from_dict(
        {
            "wallet_label": "w",
            "delimiters": ["-", ""],
            "hints": [
                {"text": "abc", "weight": 3, "position": 1},
                {"text": "", "weight": 1},
            ],  # blank text dropped
        }
    )
    assert hs.wallet_label == "w"
    assert hs.delimiters == ["-", ""]
    assert len(hs.hints) == 1
    assert hs.hints[0].required is (REQUIRED_WEIGHT <= 3)


def test_from_dict_accepts_memory_alias():
    hs = HintSet.from_dict({"wallet_label": "w", "memory": [{"text": "x", "weight": 2}]})
    assert hs.hints[0].text == "x"


def test_example_file_loads_and_targets_public_wallet():
    hs = load_hints(_EXAMPLE)
    assert hs.wallet_type == "multibit-classic"
    assert hs.delimiters == ["-"]
    assert [h.text for h in hs.hints] == ["btcr", "test", "password"]
    assert all(h.required for h in hs.hints)


def test_enrich_freeform_without_llm_is_deterministic():
    # client=None -> deterministic tokenizer only (no network).
    hints = enrich_freeform(None, "My dog Rex was born around 2013 in Denver")
    texts = {h.text for h in hints}
    assert "2013" in texts  # year captured
    assert "Rex" in texts  # non-stopword captured
    assert "Denver" in texts
    assert "was" not in texts  # stopword filtered


def test_enrich_freeform_deduplicates():
    hints = enrich_freeform(None, "river river RIVER")
    river = [h for h in hints if h.text.lower() == "river"]
    assert len(river) == 1
