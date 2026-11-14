"""Text normalization applied to every extracted block.

The goal is stable, comparable text for chunking and retrieval, not
typographic fidelity. Normalization is deterministic and idempotent.
"""

import re
import sys
import unicodedata

# Unicode "format" characters (category Cf): zero-width characters, the BOM,
# soft hyphens, bidirectional controls and tag characters. They carry no visible
# content but can disguise text or hide instructions from human reviewers, so
# they are removed. (This also drops ZWJ/ZWNJ, which can affect emoji and some
# scripts; acceptable for knowledge-base text.)
_FORMAT_CHARS = {
    code: None for code in range(sys.maxunicode + 1) if unicodedata.category(chr(code)) == "Cf"
}
# Every Unicode space separator (no-break space, em space, ...) except newline handling below.
_SPACE_LIKE = re.compile(r"[^\S\n]+")
# Control characters other than newline (tabs are handled as spaces above).
_CONTROL = re.compile(r"[\x00-\x08\x0b-\x1f\x7f-\x9f]")
# A word broken across lines with a hyphen: "infor-\nmation" -> "information".
_HYPHENATED_BREAK = re.compile(r"(?<=[a-z])-\n(?=[a-z])")
_MANY_BLANK_LINES = re.compile(r"\n{3,}")


def normalize_text(text: str) -> str:
    text = unicodedata.normalize("NFC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    text = text.translate(_FORMAT_CHARS)
    text = _SPACE_LIKE.sub(" ", text)
    text = _CONTROL.sub("", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _HYPHENATED_BREAK.sub("", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()
