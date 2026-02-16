import pytest

from retikon_core.query_engine.query_runner import rank_of_expected, top_k_overlap


def test_rank_of_expected_returns_1_based_rank() -> None:
    results = ["a", "b", "c"]
    expected = ["z", "b"]
    assert rank_of_expected(results, expected) == 2


def test_rank_of_expected_handles_no_match() -> None:
    assert rank_of_expected(["a", "b"], ["x", "y"]) is None


def test_top_k_overlap_is_fraction_of_expected_set() -> None:
    results = ["a", "b", "c", "d"]
    expected = ["b", "x", "d"]
    assert top_k_overlap(results, expected, 3) == pytest.approx(1 / 3)
