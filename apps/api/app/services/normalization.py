"""Text normalization applied to every extracted block.

The goal is stable, comparable text for chunking and retrieval, not
typographic fidelity. Normalization is deterministic and idempotent.
"""

import re
import unicodedata

# Zero-width characters and the byte-order mark carry no content.
_INVISIBLE = re.compile("[\u200b\u200c\u200d\u2060\ufeff]")
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
    text = _INVISIBLE.sub("", text)
    text = _SPACE_LIKE.sub(" ", text)
    text = _CONTROL.sub("", text)
    text = "\n".join(line.strip() for line in text.split("\n"))
    text = _HYPHENATED_BREAK.sub("", text)
    text = _MANY_BLANK_LINES.sub("\n\n", text)
    return text.strip()
