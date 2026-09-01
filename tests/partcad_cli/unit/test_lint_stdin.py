#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `pc lint --file --stdin` reads.

The buffer on standard input comes from an editor: the VS Code extension writes
the document as UTF-8 and reads this command's JSON back the same way. Python
does not agree with that on its own -- ``sys.stdin`` decodes with the locale
encoding, which is UTF-8 on Linux and macOS and the ANSI code page on Windows --
so a file with a non-ASCII character in it was checked as mojibake there, or
died in the decoder and took the findings with it. Nothing about that is visible
from a POSIX runner, which is why the encoding is pinned rather than inherited,
and why these tests hand the reader a stream that is *not* UTF-8.
"""

import io
import sys

import pytest
from partcad_cli.click.commands.lint import _read_stdin

# A description someone would really write, in characters cp1252 does not have.
TEXT = "desc: Läufer — ⌀30µm\n"


def _stdin(raw: bytes, encoding: str = "cp1252"):
    """A `sys.stdin`: text on top of bytes, decoding as the locale would."""
    return io.TextIOWrapper(io.BytesIO(raw), encoding=encoding, errors="replace")


def test_utf8_is_read_as_utf8_whatever_the_locale_says(monkeypatch):
    monkeypatch.setattr(sys, "stdin", _stdin(TEXT.encode("utf-8")))
    assert _read_stdin() == TEXT


def test_a_byte_order_mark_is_not_part_of_the_text(monkeypatch):
    # A Windows editor may write one, and it is not what column 1 of line 1 is:
    # left in, every finding on the first line would be off by one character.
    monkeypatch.setattr(sys, "stdin", _stdin(b"\xef\xbb\xbf" + TEXT.encode("utf-8")))
    assert _read_stdin() == TEXT


def test_bytes_that_are_not_utf8_are_refused_rather_than_guessed(monkeypatch):
    # Better than silently checking mojibake: the caller is told, and `pc lint`
    # turns it into a usage error rather than a traceback.
    monkeypatch.setattr(sys, "stdin", _stdin(TEXT.encode("cp1252", "replace")))
    with pytest.raises(UnicodeDecodeError):
        _read_stdin()


def test_a_stdin_with_no_binary_buffer_is_read_as_text(monkeypatch):
    # A replaced `sys.stdin` -- a test harness, an embedding -- has no `buffer`.
    monkeypatch.setattr(sys, "stdin", io.StringIO(TEXT))
    assert _read_stdin() == TEXT
