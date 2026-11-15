#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a program the client runs prints is read as the text it is, on Windows too.

'subprocess' in text mode decodes in the locale's encoding, strictly - on
Windows the ANSI code page - so a program that prints UTF-8 raised
'UnicodeDecodeError' out of 'subprocess.run' the moment it printed a character
the code page does not have, or a byte it has no character for.

The children here are real processes, because how their bytes are decoded is
the thing under test. 'TEXT' has 'И' (the byte 0x98, which code page 1251 has
no character for), 'Ё' (0x81, which 1252 has none for) and '✓' (in neither),
so these tests fail without the fix on a Windows set up for either - including
GitHub's Windows runners, which have 1252.
"""

import subprocess
import sys

import pytest

from partcad_client import client, external, ide, selfupdate

TEXT = "Иван Ёлкин ✓"


def _prints(text, stream="stdout", status=0):
    """A child that writes 'text' as UTF-8 to 'stream' and exits with 'status'."""
    script = "import sys; sys.%s.buffer.write(%s.encode('utf-8')); sys.%s.flush(); sys.exit(%d)" % (
        stream,
        ascii(text),
        stream,
        status,
    )
    return [sys.executable, "-c", script]


def test_what_docker_or_flatpak_prints_is_read_as_utf_8():
    assert external._run(_prints(TEXT)).stdout == TEXT


def test_what_an_editor_prints_is_read_as_utf_8():
    logged = []

    assert ide._run(_prints(TEXT), logged.append) == TEXT
    assert logged == [TEXT]


def test_a_launcher_that_fails_with_a_byte_the_locale_cannot_decode_still_says_why(monkeypatch):
    """The launcher prints in the locale's encoding; a byte that does not decode loses nothing.

    0x98 and 0x81 are invalid as UTF-8 and have no character in code page 1251
    or 1252 respectively, so neither Linux nor Windows decoded them strictly.
    On Windows 'subprocess' decodes in a reader thread, where the error ended
    the thread and left the stream empty: the launcher's reason for failing
    went missing from the error without a word.

    The reason is put together in the child so that the command line, which
    the error names too, cannot be what matches.
    """
    script = "import sys; sys.stderr.buffer.write(b'\\x98\\x81 ' + b'no ' + b'daemon' + b'\\n'); sys.exit(1)"
    monkeypatch.setattr(client, "launcher_argv", lambda: [sys.executable, "-c", script])

    with pytest.raises(RuntimeError) as raised:
        client.start_daemon()

    assert "no daemon" in str(raised.value)


def test_pip_is_told_to_print_utf_8_and_is_read_as_utf_8(monkeypatch):
    """pip is a Python program: in a code page it could not even print '✓'.

    The child here is not pip but Python printing 'TEXT', run with every
    argument the upgrade gives pip - its environment and how its output is
    read included.
    """
    monkeypatch.setattr(selfupdate, "_installed_distributions", lambda: ["partcad"])
    monkeypatch.setattr(selfupdate, "_pip_target_flags", list)
    real_run = subprocess.run
    script = "print(%s)" % ascii(TEXT)
    monkeypatch.setattr(selfupdate.subprocess, "run", lambda argv, **kw: real_run([sys.executable, "-c", script], **kw))
    logged = []

    selfupdate._install_wheels(None, logged.append)

    assert TEXT in logged
