from roman import from_roman, to_roman


def test_to_roman():
    assert to_roman(1) == "I"
    assert to_roman(4) == "IV"
    assert to_roman(1994) == "MCMXCIV"


def test_from_roman():
    assert from_roman("XLII") == 42
    assert from_roman("MMXXVI") == 2026
