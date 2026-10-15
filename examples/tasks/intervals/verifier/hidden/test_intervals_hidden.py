import pytest
from intervals import gaps, merge, total_length


def test_merge_empty():
    assert merge([]) == []


def test_merge_touching():
    assert merge([(1, 2), (3, 4)]) == [(1, 4)]


def test_merge_not_touching():
    assert merge([(1, 2), (4, 5)]) == [(1, 2), (4, 5)]


def test_merge_contained():
    assert merge([(1, 10), (2, 3), (4, 5)]) == [(1, 10)]


def test_merge_unsorted_chain():
    assert merge([(7, 9), (1, 3), (3, 7)]) == [(1, 9)]


def test_merge_single_point():
    assert merge([(5, 5)]) == [(5, 5)]


def test_merge_rejects_reversed():
    with pytest.raises(ValueError):
        merge([(3, 1)])


def test_total_length():
    assert total_length([]) == 0
    assert total_length([(1, 1)]) == 1
    assert total_length([(0, 9), (5, 14)]) == 15
    assert total_length([(1, 2), (10, 11)]) == 4


def test_gaps_none():
    assert gaps([(0, 10)], 2, 8) == []


def test_gaps_all():
    assert gaps([], 3, 6) == [(3, 6)]


def test_gaps_outside_window():
    assert gaps([(-5, -1), (20, 30)], 0, 10) == [(0, 10)]


def test_gaps_edges():
    assert gaps([(0, 2), (8, 10)], 0, 10) == [(3, 7)]
    assert gaps([(1, 9)], 0, 10) == [(0, 0), (10, 10)]


def test_gaps_partial_overlap_low():
    assert gaps([(-3, 2), (5, 6)], 0, 8) == [(3, 4), (7, 8)]
