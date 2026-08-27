#
# OpenVMP, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Turning what a subprocess wrote into text that can be logged.

Every runtime here reads a child's `stdout` and `stderr` off a pipe and hands
them to the logger. A pipe carries bytes, and nothing constrains those bytes to
be UTF-8: on Windows a child writes its own diagnostics in the console's code
page, so a localized message from `pip`, `venv`, `openscad` or `kicad-cli`
arrives as CP1252 or CP866 and a strict UTF-8 decode raises. That is not a
theoretical hazard -- `pc render -r` died on every Windows cell of
`Examples (PartCAD)` with

    UnicodeDecodeError: 'utf-8' codec can't decode byte 0xd7 in position 87

with the whole render lost to one byte inside a message the code was only ever
going to log.

So decode leniently, the way `shape.py` reads a source file it did not write.
An undecodable byte becomes U+FFFD and the rest of the message survives, which
is the same bargain `brand.py` struck in #550 for a file that is not text: a
stream we cannot read perfectly must not abort the work it was describing.

Deliberately no attempt to guess the code page. CP1252 and its neighbours
decode almost any byte sequence without complaint, so a guess does not fail
where it is wrong -- it silently returns plausible mojibake, and shadows the
ordinary case of UTF-8 with one bad byte in it. Marking the bytes we could not
read is worth more in a diagnostic than inventing characters for them.
"""


def decode(data: bytes) -> str:
    """Decode subprocess output as UTF-8, marking anything that is not."""
    if data is None:
        return data
    return data.decode("utf-8", errors="replace")
