"""Normalisation for untrusted supplier text before security scanning."""

from __future__ import annotations

import re
import unicodedata

_ZERO_WIDTH_RE = re.compile(
    "[\u00ad\u034f\u061c\u115f\u1160\u17b4\u17b5\u180b-\u180f"
    "\u200b-\u200f\u202a-\u202e\u2060-\u206f\ufeff\ufff9-\ufffb]"
)
_HTML_TAG_RE = re.compile(r"<(?!\!--)[^>]{0,200}>")


def normalise_untrusted_text(text: str) -> str:
    """Normalise compatibility characters and remove common obfuscation.

    Full-width characters become ASCII under NFKC; zero-width and bidi controls
    disappear; HTML-like tags are replaced by spaces so words on either side do
    not become glued together.  Homoglyph substitution (e.g. Cyrillic 'І' for
    Latin 'I') is deliberately not attempted here because it would damage
    legitimate non-Latin language detection; that remains a documented limit.
    """

    result = unicodedata.normalize("NFKC", text)
    result = _ZERO_WIDTH_RE.sub("", result)
    result = _HTML_TAG_RE.sub(" ", result)
    result = result.replace("\u00a0", " ")
    return result
