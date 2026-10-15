"""Interval arithmetic over closed integer ranges."""


def merge(intervals):
    """Merge overlapping or touching [start, end] ranges into a sorted list of tuples."""
    result = []
    for start, end in sorted(intervals):
        if start > end:
            raise ValueError(f"empty interval ({start}, {end})")
        if result and start <= result[-1][1] + 1:
            last_start, last_end = result[-1]
            result[-1] = (last_start, max(last_end, end))
        else:
            result.append((start, end))
    return result


def total_length(intervals):
    """Number of integers covered by the union of the ranges."""
    return sum(end - start + 1 for start, end in merge(intervals))


def gaps(intervals, lo, hi):
    """Ranges inside [lo, hi] that no interval covers."""
    out = []
    cursor = lo
    for start, end in merge(intervals):
        if end < lo or start > hi:
            continue
        if start > cursor:
            out.append((cursor, start - 1))
        cursor = max(cursor, end + 1)
    if cursor <= hi:
        out.append((cursor, hi))
    return out
