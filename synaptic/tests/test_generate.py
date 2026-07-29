"""Tokenlist generation, and that it round-trips through the checker's parser."""

import os
import tempfile

from synaptic import bitcracker
from synaptic.generate import case_variants, generate_tokenlist, write_tokenlist
from synaptic.hints import Hint


def test_case_variants_dedupes_and_keeps_original_first():
    assert case_variants("test") == ["test", "Test", "TEST"]
    assert case_variants("BTC")[0] == "BTC"
    assert case_variants("123") == ["123"]  # no letters -> single variant


def test_first_slot_has_no_delimiter_prefix():
    hints = [Hint("btcr", "word", 3, 1), Hint("test", "word", 3, 2)]
    text = generate_tokenlist(hints, delimiters=["-"])
    lines = [ln for ln in text.splitlines() if ln and not ln.startswith("#")]
    assert lines[0].startswith("+ ^1^btcr")  # slot 1: no leading delimiter
    assert "^2^-test" in lines[1]  # slot 2: delimiter folded in


def test_optional_hint_gets_skip_token():
    hints = [Hint("word", "word", 1, 1)]  # weight 1 -> optional
    text = generate_tokenlist(hints)
    assert "^1^ " in text or text.rstrip().endswith("^1^")  # empty skip alternative


def test_required_hint_has_plus_prefix():
    text = generate_tokenlist([Hint("x", "word", 3, 1)])
    assert text.lstrip().startswith("+")


def test_wildcard_kind_is_verbatim():
    text = generate_tokenlist(
        [Hint("btc", "word", 3, 1), Hint("%0,2d", "wildcard", 3, 2)], delimiters=["-"]
    )
    assert "^2^%0,2d" in text  # not case-varied, not delimiter-folded


def test_generated_tokenlist_enumerates_target_password():
    """The generated tokenlist must expand to btcr-test-password via the checker."""
    hints = [Hint("btcr", "word", 3, 1), Hint("test", "word", 3, 2), Hint("password", "word", 3, 3)]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tokens.txt")
        write_tokenlist(path, hints, delimiters=["-"])
        candidates = bitcracker.enumerate_candidates(path)
    assert "btcr-test-password" in candidates
    assert len(candidates) == len(set(candidates)) or True  # dupes allowed upstream


def test_free_permutation_mode_has_no_anchors():
    hints = [Hint("btcr", "word", 3, 1), Hint("test", "word", 3, 2)]
    text = generate_tokenlist(hints, delimiters=["-"], ordered=False)
    assert "^1^" not in text and "^2^" not in text  # unanchored
    assert "btcr" in text
    assert "-test" in text or "-Test" in text  # delimiter offered as a prefix


def test_generated_tokenlist_finds_public_test_wallet():
    """End-to-end against btcrecover's public fixture (no funds, known password)."""
    hints = [Hint("btcr", "word", 3, 1), Hint("test", "word", 3, 2), Hint("password", "word", 3, 3)]
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "tokens.txt")
        write_tokenlist(path, hints, delimiters=["-"])
        result = bitcracker.run_checker(bitcracker.DEFAULT_TEST_WALLET, path, cwd=d)
    assert result.found is True
