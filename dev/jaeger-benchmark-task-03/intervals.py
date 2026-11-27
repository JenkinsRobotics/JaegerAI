def total_covered(intervals):
    """Return the union length of half-open integer intervals.

    Accepts any iterable (including generators), tolerates zero-length
    intervals, and raises ValueError on any reversed interval (start > end).
    Runs in O(n log n) time and does not mutate the input.
    """
    # Materialize into a new list so generators work and the input is untouched.
    items = list(intervals)

    parsed = []
    for start, end in items:
        if start > end:
            raise ValueError(f"reversed interval: ({start}, {end})")
        parsed.append((start, end))

    # Sort a copy by start (then end); sorting the new list leaves input intact.
    parsed.sort()

    total = 0
    cur_start = None
    cur_end = None
    for start, end in parsed:
        if cur_end is None or start > cur_end:
            # Disjoint (or first) interval: close the current run and start a new one.
            if cur_end is not None:
                total += cur_end - cur_start
            cur_start, cur_end = start, end
        else:
            # Overlapping or touching: extend the current run if needed.
            if end > cur_end:
                cur_end = end
    if cur_end is not None:
        total += cur_end - cur_start

    return total
