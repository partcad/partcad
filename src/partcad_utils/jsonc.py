#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""JSON with comments, as editors and coding agents write their settings.

`launch.json`, Zed's `settings.json` and the like are "JSON with comments":
`//` and `/* */` comments, and trailing commas, which `json` refuses. Two
things read such files and have to agree on what is in them: `pc init`, editing
`.vscode/launch.json` (`partcad.launch_config`), and `pc mcp --root`, finding the
agent configuration that names its root (`partcad_utils.agent_config`) -- in a
file a person may have commented, as the documentation tells a Zed user to do.

Reading only. A file with comments is never rewritten from a parsed copy, which
would drop them; `partcad.launch_config` edits such a file as text, and the MCP
installer leaves one alone.
"""

import json
import re
from typing import Any


def blank_json_comments(text: str) -> str:
    """Return `text` with every `//` and `/* */` comment replaced by blanks.

    `launch.json` is "JSON with comments", which `json` refuses to parse -- and
    Visual Studio Code puts three comment lines in the file it generates, so
    this is the common case rather than the exotic one. String literals are
    tracked so that a `//` inside a URL survives.

    The comments are replaced character for character, and newlines are kept, so
    that the result is the same length as the input and every offset in it is an
    offset in the original file. Whitespace is nothing to JSON and everything to
    an edit that has to land in the right place.
    """
    out: list[str] = []
    index = 0
    length = len(text)
    in_string = False
    while index < length:
        char = text[index]

        if in_string:
            out.append(char)
            if char == "\\" and index + 1 < length:
                out.append(text[index + 1])
                index += 2
                continue
            if char == '"':
                in_string = False
            index += 1
            continue

        if char == '"':
            in_string = True
            out.append(char)
            index += 1
            continue

        if char == "/" and index + 1 < length:
            if text[index + 1] == "/":
                while index < length and text[index] != "\n":
                    out.append(" ")
                    index += 1
                continue
            if text[index + 1] == "*":
                end = text.find("*/", index + 2)
                end = length if end == -1 else end + 2
                out.extend("\n" if text[i] == "\n" else " " for i in range(index, end))
                index = end
                continue

        out.append(char)
        index += 1

    return "".join(out)


def _drop_trailing_commas(text: str) -> str:
    """Remove the commas that JSON forbids and editors leave behind."""
    return re.sub(r",(\s*[}\]])", r"\1", text)


def loads(text: str) -> Any:
    """Parse JSON with comments and trailing commas."""
    return json.loads(_drop_trailing_commas(blank_json_comments(text)))
