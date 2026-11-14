import pytest

from app.services.normalization import normalize_text


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("cafe\u0301", "caf\u00e9"),  # NFC
        ("a\r\nb\rc", "a\nb\nc"),  # line endings
        ("tab\there", "tab here"),
        ("no\u00a0break\u2003space", "no break space"),  # Unicode spaces
        ("zero\u200bwidth\ufeff", "zerowidth"),
        ("bell\x07 and nul\x00", "bell and nul"),
        ("  padded line  \n  next  ", "padded line\nnext"),
        ("many    spaces", "many spaces"),
        ("para one\n\n\n\n\npara two", "para one\n\npara two"),
        ("infor-\nmation", "information"),  # line-break hyphenation
        ("well-known\nterm", "well-known\nterm"),  # real hyphen kept
        ("Phase-\n2", "Phase-\n2"),  # not between lowercase letters: kept
        ("\n\n  surrounded  \n\n", "surrounded"),
        ("", ""),
    ],
)
def test_normalize_text(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected


def test_normalization_is_idempotent() -> None:
    raw = " A\u00a0b \r\n\r\n\r\n infor-\nmation \u200b"

    once = normalize_text(raw)
    assert normalize_text(once) == once


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("co\u00adoperate", "cooperate"),  # soft hyphen
        ("safe \u202eevil", "safe evil"),  # right-to-left override
        ("\U000e0041hidden\U000e007f text", "hidden text"),  # tag characters
        ("arabic\u061cmark", "arabicmark"),  # Arabic letter mark (bidi)
        ("\u2066isolated\u2069", "isolated"),  # bidi isolates
    ],
)
def test_format_characters_are_removed(raw: str, expected: str) -> None:
    assert normalize_text(raw) == expected
