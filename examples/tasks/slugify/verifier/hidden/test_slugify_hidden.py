import pytest
from slugify import slugify


@pytest.mark.parametrize(
    "text, expected",
    [
        ("Hello World", "hello-world"),
        ("  leading and trailing  ", "leading-and-trailing"),
        ("Rust, Go & Python!", "rust-go-python"),
        ("Café déjà vu", "cafe-deja-vu"),
        ("ALL CAPS 2024", "all-caps-2024"),
        ("", ""),
        ("!!!", ""),
        ("a--b__c", "a-b-c"),
    ],
)
def test_cases(text, expected):
    assert slugify(text) == expected


def test_cut_at_word_boundary():
    assert slugify("one two three four", max_length=13) == "one-two-three"
    assert slugify("one two three four", max_length=12) == "one-two"


def test_exact_fit():
    assert slugify("abc def", max_length=7) == "abc-def"


def test_single_long_word_is_truncated():
    assert slugify("supercalifragilistic", max_length=5) == "super"


def test_custom_separator():
    assert slugify("Hello Big World", separator="_") == "hello_big_world"


def test_default_max_length():
    slug = slugify("word " * 40)
    assert len(slug) == 49
    assert slug.endswith("word")
