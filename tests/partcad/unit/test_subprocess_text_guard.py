#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Every program PartCAD runs in text mode has its output decoded as somebody decided.

'subprocess' in text mode ('text=True', 'universal_newlines=True') decodes what
a program prints in the locale's encoding, and strictly: on Windows a code page,
in which a program printing UTF-8 - Docker, an editor, cadmpeg - raises
'UnicodeDecodeError' out of the call on the first character the code page does
not have. So a call says which encoding the program prints ('encoding=') or, if
the locale's is right, that a byte it cannot decode is not fatal ('errors=').
"""

import ast
import pathlib

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCES = REPO_ROOT / "src"

RUNNERS = {"run", "Popen", "check_output", "call", "check_call"}


def undecided_text_mode_calls(source, filename="<source>"):
    """The line of each subprocess call in 'source' that reads text without saying how to decode it."""
    found = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        name = func.attr if isinstance(func, ast.Attribute) else getattr(func, "id", None)
        if name not in RUNNERS:
            continue
        keywords = {keyword.arg: keyword.value for keyword in node.keywords}
        text_mode = any(
            isinstance(keywords.get(key), ast.Constant) and keywords[key].value is True
            for key in ("text", "universal_newlines")
        )
        # '**kwargs' may say it; 'encoding' or 'errors' alone already means text mode.
        if text_mode and not {"encoding", "errors", None} & set(keywords):
            found.append(node.lineno)
    return found


@pytest.mark.parametrize(
    "source, lines",
    [
        ("subprocess.run(argv, text=True)", [1]),
        ("subprocess.run(argv, capture_output=True, universal_newlines=True)", [1]),
        ("subprocess.Popen(argv, stdout=PIPE, text=True)", [1]),
        ("subprocess.check_output(argv, text=True)", [1]),
        ("run(argv, text=True)", [1]),
        ("subprocess.run(argv, text=True, encoding='utf-8')", []),
        ("subprocess.run(argv, text=True, errors='replace')", []),
        ("subprocess.run(argv, capture_output=True)", []),
        ("subprocess.run(argv, text=False)", []),
        ("subprocess.run(argv, **options)", []),
        ("subprocess.run(argv, text=mode)", []),
    ],
)
def test_the_guard_tells_a_text_mode_call_that_does_not_say_how_to_decode(source, lines):
    assert undecided_text_mode_calls(source) == lines


def test_every_program_partcad_reads_text_from_is_decoded_as_decided():
    """Say 'encoding="utf-8", errors="replace"' for a program that prints UTF-8,
    and 'errors="replace"' for one that prints in the locale's encoding."""
    found = [
        "%s:%d" % (path.relative_to(REPO_ROOT).as_posix(), line)
        for path in sorted(SOURCES.rglob("*.py"))
        for line in undecided_text_mode_calls(path.read_text(encoding="utf-8"), str(path))
    ]

    assert found == []
