"""Roman numeral conversion for 1..3999."""

NUMERALS = [
    (1000, "M"), (900, "CM"), (500, "D"), (400, "CD"),
    (100, "C"), (90, "XC"), (50, "L"), (40, "XL"),
    (10, "X"), (9, "IX"), (5, "V"), (4, "IV"), (1, "I"),
]


def to_roman(n):
    if not isinstance(n, int) or isinstance(n, bool) or not 1 <= n <= 3999:
        raise ValueError(f"cannot convert {n!r}")
    parts = []
    for value, symbol in NUMERALS:
        count, n = divmod(n, value)
        parts.append(symbol * count)
    return "".join(parts)


def from_roman(s):
    if not s:
        raise ValueError("empty numeral")
    s = s.upper()
    total = 0
    i = 0
    for value, symbol in NUMERALS:
        while s.startswith(symbol, i):
            total += value
            i += len(symbol)
    if i != len(s) or to_roman(total) != s:
        raise ValueError(f"invalid numeral {s!r}")
    return total
