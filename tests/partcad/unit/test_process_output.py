#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Decoding what a subprocess wrote, when it did not write UTF-8."""

import pytest

from partcad.process_output import decode

# The exact shape of the bytes that killed `pc render -r` on every Windows cell
# of `Examples (PartCAD)`: a message whose 88th byte is not valid UTF-8, which
# is what a child writing in the console's code page produces.
CI_FAILURE = b"x" * 87 + b"\xd7" + b" and the rest of the message"


def test_the_byte_that_aborted_the_windows_render_no_longer_raises():
    """A strict decode raises here; this is the whole of the bug."""
    with pytest.raises(UnicodeDecodeError):
        CI_FAILURE.decode()

    assert decode(CI_FAILURE).endswith(" and the rest of the message")


def test_only_the_undecodable_byte_is_lost():
    """The rest of a diagnostic has to survive, or logging it is pointless."""
    decoded = decode(CI_FAILURE)
    assert decoded.count("�") == 1
    assert decoded.startswith("x" * 87)


@pytest.mark.parametrize(
    "encoding, text",
    [
        ("cp1252", "Fichier introuvable"),
        ("cp1251", "Файл не найден"),
        ("cp866", "Файл не найден"),
    ],
)
def test_a_message_in_a_windows_code_page_survives_as_text(encoding, text):
    """Whatever the child used, the parent gets a string and keeps going."""
    decoded = decode(text.encode(encoding))
    assert isinstance(decoded, str)
    # The ASCII skeleton of a message is what makes it findable in a log.
    for word in text.split():
        if word.isascii():
            assert word in decoded


def test_clean_utf_8_is_returned_unchanged():
    """The ordinary case must not be degraded by the lenient one."""
    for text in ("", "plain ascii", "héllo — ünicode ✓", "多字节"):
        assert decode(text.encode("utf-8")) == text


def test_none_passes_through():
    """Callers hand this whatever `communicate()` gave them."""
    assert decode(None) is None
