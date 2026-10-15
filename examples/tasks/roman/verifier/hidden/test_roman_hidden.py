import pytest
from roman import from_roman, to_roman

KNOWN = {
    1: "I", 3: "III", 4: "IV", 5: "V", 9: "IX", 14: "XIV", 40: "XL", 44: "XLIV",
    90: "XC", 400: "CD", 444: "CDXLIV", 900: "CM", 1666: "MDCLXVI", 3999: "MMMCMXCIX",
}


@pytest.mark.parametrize("n, s", sorted(KNOWN.items()))
def test_known(n, s):
    assert to_roman(n) == s
    assert from_roman(s) == n


def test_round_trip_all():
    for n in range(1, 4000):
        assert from_roman(to_roman(n)) == n


def test_lowercase_accepted():
    assert from_roman("mcmxciv") == 1994


@pytest.mark.parametrize("bad", [0, 4000, -1, 2.5, "7", True])
def test_to_roman_rejects(bad):
    with pytest.raises(ValueError):
        to_roman(bad)


@pytest.mark.parametrize("bad", ["", "IIII", "VX", "IC", "MMMM", "ABC", "XIIV"])
def test_from_roman_rejects(bad):
    with pytest.raises(ValueError):
        from_roman(bad)
