#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""PartCAD reads and writes its text files as UTF-8, whatever the locale says.

Python's 'open()' without an 'encoding' uses the locale's, which on Windows is
a code page: 1252 in Western Europe, 1251 for Cyrillic, and so on. So a README
or an instruction book with a character the code page lacks failed to be
written ('UnicodeEncodeError: 'charmap' codec can't encode character'), and a
'partcad.yaml' that 'pc add' edited was read and written in an encoding other
than the UTF-8 it is loaded as.

The behaviour tests below use Cyrillic, which code page 1252 - the one
GitHub's Windows runners have - cannot encode, so that they fail there and not
only on a machine set up for another language. The last test is the guard: it
finds every text-mode 'open()' in the sources that does not say which encoding.
"""

import ast
import asyncio
import locale
import pathlib

import pytest

import partcad as pc
from partcad import document as pc_document
from partcad_utils import user_config

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
SOURCES = REPO_ROOT / "src"

TEXT = "Плата 85 × 56 мм, Ø 2.75"


def _project(tmp_path, yaml_text):
    (tmp_path / "partcad.yaml").write_text(yaml_text, encoding="utf-8")
    return pc.Context(str(tmp_path)).get_project("//")


def test_a_readme_is_written_as_utf_8(tmp_path):
    project = _project(tmp_path, "desc: %s\nparts:\n  box:\n    type: step\n    desc: %s\n" % (TEXT, TEXT))
    # Never read: the README needs the part declared and its picture rendered.
    (tmp_path / "box.step").write_text("", encoding="utf-8")
    out = tmp_path / "out"
    out.mkdir()
    (out / "box.svg").write_text("<svg/>", encoding="utf-8")

    # Named '..._async' but synchronous; it is the one that writes the file.
    project.render_readme_async({"svg": {}, "readme": {}}, str(out))

    assert TEXT in (out / "README.md").read_bytes().decode("utf-8")


def test_an_html_document_is_written_as_utf_8(tmp_path):
    project = _project(tmp_path, "desc: A package\n")
    document = pc_document.Document(title=TEXT, pages=[pc_document.Page(blocks=[pc_document.Paragraph(text=TEXT)])])
    path = tmp_path / "guide.html"

    asyncio.run(project._write_document_async(document, "html", str(path)))

    assert TEXT in path.read_bytes().decode("utf-8")


def test_an_object_added_to_partcad_yaml_keeps_what_is_there_in_utf_8(tmp_path):
    project = _project(tmp_path, "desc: %s\n" % TEXT)

    assert project.add_object_config("parts", "board", {"type": "step", "desc": TEXT})

    written = (tmp_path / "partcad.yaml").read_bytes().decode("utf-8")
    assert written.count(TEXT) == 2, written
    reloaded = pc.Context(str(tmp_path)).get_project("//")
    assert reloaded.desc == TEXT
    assert reloaded.config_obj["parts"]["board"]["desc"] == TEXT


def test_a_configuration_file_is_read_as_utf_8(tmp_path):
    path = tmp_path / "config.yaml"
    path.write_bytes(("cacheDir: C:\\Users\\Иван\\cache\n").encode("utf-8"))

    assert user_config.read_config_text(path) == "cacheDir: C:\\Users\\Иван\\cache\n"


def test_a_configuration_file_an_older_version_wrote_in_the_locales_encoding_still_reads(tmp_path, monkeypatch):
    """What older versions wrote on a Windows set up for Cyrillic is not thrown away."""
    path = tmp_path / "config.yaml"
    path.write_bytes(("cacheDir: C:\\Users\\Иван\\cache\n").encode("cp1251"))
    monkeypatch.setattr(locale, "getpreferredencoding", lambda do_setlocale=True: "cp1251")

    assert user_config.read_config_text(path) == "cacheDir: C:\\Users\\Иван\\cache\n"


#
# The guard
#

# Calls named 'open' that do not open a text file.
NOT_TEXT_FILES = {"tarfile", "zipfile", "webbrowser", "Image"}


def _mode(call, index):
    """The mode an open-like call is given: 'r' when none is, None when it is not a literal."""
    if len(call.args) > index:
        arg = call.args[index]
        return arg.value if isinstance(arg, ast.Constant) and isinstance(arg.value, str) else None
    for keyword in call.keywords:
        if keyword.arg == "mode":
            return keyword.value.value if isinstance(keyword.value, ast.Constant) else None
    return "r"


def unencoded_text_opens(source, filename="<source>"):
    """The line of each call in 'source' that opens a file as text without saying which encoding."""
    found = []
    for node in ast.walk(ast.parse(source, filename)):
        if not isinstance(node, ast.Call):
            continue
        keywords = {keyword.arg for keyword in node.keywords}
        if "encoding" in keywords or None in keywords:  # '**kwargs' may carry it
            continue
        func = node.func
        if isinstance(func, ast.Name) and func.id == "open":
            mode = _mode(node, 1)
        elif isinstance(func, ast.Attribute) and func.attr == "fdopen":
            mode = _mode(node, 1)
        elif isinstance(func, ast.Attribute) and func.attr == "open":
            if isinstance(func.value, ast.Name) and func.value.id in NOT_TEXT_FILES:
                continue
            # 'io.open(path, mode)', or 'Path.open(mode)' and the like.
            io_open = isinstance(func.value, ast.Name) and func.value.id == "io"
            mode = _mode(node, 1 if io_open else 0)
        elif isinstance(func, ast.Attribute) and func.attr == "read_text" and not node.args:
            mode = "r"
        elif isinstance(func, ast.Attribute) and func.attr == "write_text" and len(node.args) < 2:
            mode = "w"
        else:
            continue
        # A mode that is not a literal cannot be judged; one with 'b' in it is bytes.
        if mode is not None and "b" not in mode:
            found.append(node.lineno)
    return found


@pytest.mark.parametrize(
    "source, lines",
    [
        ("open(p)", [1]),
        ("open(p, 'w')", [1]),
        ("open(p, mode='a')", [1]),
        ("os.fdopen(fd, 'w')", [1]),
        ("io.open(p, 'r')", [1]),
        ("path.open('w')", [1]),
        ("path.read_text()", [1]),
        ("path.write_text(text)", [1]),
        ("open(p, encoding='utf-8')", []),
        ("open(p, 'w', encoding='utf-8')", []),
        ("path.read_text(encoding='utf-8')", []),
        ("path.write_text(text, encoding='utf-8')", []),
        ("path.write_text(text, 'utf-8')", []),
        ("open(p, 'rb')", []),
        ("open(p, 'xb')", []),
        ("path.open('wb')", []),
        ("open(p, mode)", []),
        ("open(p, **options)", []),
        ("tarfile.open(fileobj=f, mode='r:gz')", []),
        ("webbrowser.open(url)", []),
    ],
)
def test_the_guard_tells_a_text_open_without_an_encoding(source, lines):
    assert unencoded_text_opens(source) == lines


def test_every_text_file_partcad_opens_says_its_encoding():
    """No text-mode 'open()' in the sources leaves the encoding to the locale.

    Give it 'encoding="utf-8"'; a file that has to be read in some other
    encoding says which.
    """
    found = [
        "%s:%d" % (path.relative_to(REPO_ROOT).as_posix(), line)
        for path in sorted(SOURCES.rglob("*.py"))
        for line in unencoded_text_opens(path.read_text(encoding="utf-8"), str(path))
    ]

    assert found == []
