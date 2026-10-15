from intervals import gaps, merge, total_length


def test_merge_overlapping():
    assert merge([(1, 3), (2, 6)]) == [(1, 6)]


def test_merge_disjoint():
    assert merge([(8, 10), (1, 2)]) == [(1, 2), (8, 10)]


def test_total_length():
    assert total_length([(1, 3), (2, 6)]) == 6


def test_gaps():
    assert gaps([(2, 3)], 0, 5) == [(0, 1), (4, 5)]
