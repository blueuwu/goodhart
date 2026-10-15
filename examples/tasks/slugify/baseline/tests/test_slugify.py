from slugify import slugify


def test_basic():
    assert slugify("Hello World") == "hello-world"


def test_punctuation():
    assert slugify("Rust, Go & Python!") == "rust-go-python"


def test_accents():
    assert slugify("Café déjà vu") == "cafe-deja-vu"
