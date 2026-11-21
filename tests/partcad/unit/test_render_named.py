#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a render or an export of named objects writes, and what it says when it writes nothing.

A 'kicad' part is not finalized unless it says otherwise, and a run over a whole
package leaves such a part out. 'Project.render_async' used to leave it out of a
request that named it too, without a word: 'pc render -t png Arduino_Nano' and
'pc export -t step Arduino_Nano' in 'examples/produce_part_kicad' ended well,
having written nothing. Naming an object is asking for it, so it is written; and
a named object that is written as no file type at all, for whatever reason, is
reported as an error rather than passed over.

Nothing is built: the work a shape would be put to is replaced by a recording,
and what is under test is which shapes are handed to it and what is said
around it. So none of this needs a CAD sandbox, or KiCad.
"""

import asyncio
import logging

import pytest

import partcad as pc
from partcad.shape import Shape

PACKAGE = """\
parts:
  cube:
    type: cadquery
  board:
    type: kicad

interfaces:
  mount:
    desc: A way to hold a board

render:
  svg:
"""


def _context(tmp_path, config=PACKAGE):
    package = tmp_path / "package"
    package.mkdir()
    (package / "partcad.yaml").write_text(config)
    (package / "cube.py").write_text("raise AssertionError('nothing is built here')\n")
    return pc.Context(str(package))


@pytest.fixture
def rendered(monkeypatch):
    """The shapes handed over to be written, by name, with the file types asked of each."""
    calls = []

    async def render_async(self, ctx, format_name, **kwargs):
        calls.append((self.name, list(format_name)))

    monkeypatch.setattr(Shape, "render_async", render_async)
    return calls


def _render(ctx, caplog, **kwargs):
    with caplog.at_level(logging.INFO, logger="partcad"):
        asyncio.run(ctx.get_project("//").render_async(**kwargs))
    return [r.getMessage() for r in caplog.records if r.levelno >= logging.ERROR]


def test_a_kicad_part_is_not_finalized(tmp_path):
    ctx = _context(tmp_path)

    assert ctx._get_part(":board").finalized is False
    assert ctx._get_part(":cube").finalized is True


def test_a_part_that_is_not_finalized_is_written_when_it_is_named(tmp_path, rendered, caplog):
    errors = _render(_context(tmp_path), caplog, parts=["board"], format="png")

    assert rendered == [("board", ["png"])]
    assert errors == []


def test_with_no_file_type_named_it_is_written_as_the_ones_configured(tmp_path, rendered, caplog):
    errors = _render(_context(tmp_path), caplog, parts=["board"])

    assert rendered == [("board", ["svg"])]
    assert errors == []


def test_a_run_over_the_whole_package_leaves_it_out_and_says_so(tmp_path, rendered, caplog):
    errors = _render(_context(tmp_path), caplog, format="svg")

    assert rendered == [("cube", ["svg"])]
    assert errors == []
    assert any(
        r.levelno == logging.INFO
        and "Skipping the part '//:board'" in r.getMessage()
        and "a 'kicad' part is not finalized" in r.getMessage()
        for r in caplog.records
    )


def test_a_named_object_with_no_file_type_configured_is_an_error(tmp_path, rendered, caplog):
    ctx = _context(tmp_path, PACKAGE.replace("render:\n  svg:\n", ""))

    errors = _render(ctx, caplog, parts=["cube"])

    assert rendered == []
    assert errors == [
        "Nothing is written for the part '//:cube': no file type it can be written as is declared for it "
        "under 'render:' or 'export:'. Name one with '-t'"
    ]


def test_a_file_type_that_excludes_the_kind_is_given_as_the_reason(tmp_path, rendered, caplog):
    ctx = _context(tmp_path, PACKAGE.replace("  svg:\n", "  svg:\n    exclude: [parts]\n"))

    errors = _render(ctx, caplog, parts=["cube"], format="svg")

    assert rendered == []
    assert errors == ["Nothing is written for the part '//:cube': the file type 'svg' is configured to exclude parts"]


def test_an_instruction_book_of_a_part_is_an_error(tmp_path, rendered, caplog):
    errors = _render(_context(tmp_path), caplog, parts=["cube"], format="pdf")

    assert rendered == []
    assert errors == [
        "Nothing is written for the part '//:cube': 'pdf' is a document PartCAD writes of a package or an "
        "assembly, not a file of a part"
    ]


def test_the_package_document_asked_for_is_what_was_written(tmp_path, rendered, caplog):
    """'pc render -t readme cube' writes the package README, which is what lists the part."""
    out = tmp_path / "out"
    out.mkdir()

    errors = _render(_context(tmp_path), caplog, parts=["cube"], format="readme", output_dir=str(out))

    assert rendered == []
    assert errors == []
    assert (out / "README.md").exists()


def test_a_named_interface_is_an_error(tmp_path, rendered, caplog):
    errors = _render(_context(tmp_path), caplog, interfaces=["mount"], format="svg")

    assert rendered == []
    assert errors == [
        "Nothing is written for the interface '//:mount': an interface is a set of ports, with no geometry of its "
        "own to write"
    ]


def test_a_named_object_of_a_skipped_package_says_why_nothing_is_written(tmp_path, rendered, caplog):
    ctx = _context(tmp_path)
    project = ctx.get_project("//")
    project.skipped = True
    project.skipped_by = "arm and useDocker"

    errors = _render(ctx, caplog, parts=["board"], format="png")

    assert rendered == []
    # Not an error: an exclusion by 'unless' never is.
    assert errors == []
    assert any(
        "Nothing is written for the part '//:board': its package is excluded by 'unless' (arm and useDocker)"
        in r.getMessage()
        for r in caplog.records
    )


def test_qualifying_the_whole_package_leaves_it_out_and_says_so(tmp_path, caplog):
    ctx = _context(tmp_path)

    with caplog.at_level(logging.INFO, logger="partcad"):
        assert asyncio.run(ctx.get_project("//").test_async(ctx, tests=[])) is True

    assert any("Skipping the part '//:board'" in r.getMessage() for r in caplog.records)
    assert not any("'//:cube'" in r.getMessage() for r in caplog.records if "Skipping" in r.getMessage())
