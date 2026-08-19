#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Reader for the dialect of JSON that Visual Studio Code writes.

`.vscode/extensions.json`, `product.json` and every other file this component
reads or rewrites are "JSON with comments": ordinary JSON plus `//` and `/* */`
comments and trailing commas. `json.loads` rejects all three, so the input is
normalized here first. Comments are stripped rather than preserved: nothing in
this component writes a file back to where a human keeps comments -- the files
it writes are inside the built application.
"""

import json
from typing import Any


def strip_json_comments(text: str) -> str:
    """Return `text` with comments removed and trailing commas dropped.

    String literals are tracked so that a `//` or `/*` inside one, and an escaped
    quote before one, are left alone.
    """
    out: list[str] = []
    i = 0
    length = len(text)
    in_string = False
    while i < length:
        char = text[i]

        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < length:
                # Copy the escaped character as-is; it can be a quote.
                out.append(text[i + 1])
                i += 2
                continue
            if char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue

        if char == "/" and i + 1 < length:
            if text[i + 1] == "/":
                while i < length and text[i] != "\n":
                    i += 1
                continue
            if text[i + 1] == "*":
                end = text.find("*/", i + 2)
                i = length if end == -1 else end + 2
                continue

        out.append(char)
        i += 1

    return _drop_trailing_commas("".join(out))


def _drop_trailing_commas(text: str) -> str:
    """Remove commas that are followed only by whitespace and a `}` or `]`."""
    out: list[str] = []
    in_string = False
    i = 0
    length = len(text)
    while i < length:
        char = text[i]

        if in_string:
            out.append(char)
            if char == "\\" and i + 1 < length:
                out.append(text[i + 1])
                i += 2
                continue
            if char == '"':
                in_string = False
            i += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            i += 1
            continue

        if char == ",":
            j = i + 1
            while j < length and text[j].isspace():
                j += 1
            if j < length and text[j] in "}]":
                # Drop the comma, keep the whitespace so line numbers survive.
                out.append(text[i + 1 : j])
                i = j
                continue

        out.append(char)
        i += 1

    return "".join(out)


def loads(text: str) -> Any:
    """Parse JSON-with-comments text."""
    return json.loads(strip_json_comments(text))


def load(path) -> Any:
    """Parse a JSON-with-comments file."""
    with open(path, "r", encoding="utf-8") as handle:
        return loads(handle.read())
