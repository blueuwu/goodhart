"""Turn arbitrary titles into URL slugs."""

import re
import unicodedata


def slugify(text, max_length=50, separator="-"):
    """Lowercase ASCII words joined by `separator`, cut at a word boundary."""
    text = unicodedata.normalize("NFKD", text)
    text = text.encode("ascii", "ignore").decode("ascii")
    words = re.findall(r"[a-z0-9]+", text.lower())
    slug = ""
    for word in words:
        candidate = word if not slug else slug + separator + word
        if len(candidate) > max_length:
            break
        slug = candidate
    if not slug and words:
        slug = words[0][:max_length]
    return slug
