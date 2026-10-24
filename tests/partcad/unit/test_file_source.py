#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where an object's file is, and what PartCAD does with it, decided once for every kind.

'partcad.file_source' holds what the part, sketch and assembly file factories
used to repeat three times -- resolving 'path' and refusing one that cannot be
the object's file -- and the class that says whether the file is handed over as
it is, rendered as a template, or bytes.
"""

import pytest
import yaml

import partcad as pc
from partcad.file_source import BinarySourceFile, SourceFile, TemplateSourceFile


def _package(tmp_path, section, objects):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test", section: objects}))
    return pc.Context(str(tmp_path))


def test_a_file_that_is_not_there_is_refused_by_kind(tmp_path):
    ctx = _package(tmp_path, "parts", {"cube": {"type": "step"}})
    with pytest.raises(Exception, match=r"The part path \(.*cube\.step\) must exist"):
        pc.factory.instantiate(
            "part",
            "step",
            ctx,
            ctx.get_project("//test"),
            ctx.get_project("//test"),
            {
                "name": "cube",
                "type": "step",
                "orig_name": "cube",
            },
        )


def test_a_directory_is_not_a_file_whatever_fetches_it(tmp_path):
    """With 'fileFrom' or without: a path that exists and is a directory is a broken declaration."""
    (tmp_path / "outline.svg").mkdir()
    ctx = _package(tmp_path, "sketches", {"outline": {"type": "svg"}})
    project = ctx.get_project("//test")
    with pytest.raises(Exception, match=r"The sketch path \(.*outline\.svg\) must be a file"):
        pc.factory.instantiate(
            "sketch",
            "svg",
            ctx,
            project,
            project,
            {"name": "outline", "type": "svg", "orig_name": "outline", "fileFrom": "url", "fileUrl": "http://x/y"},
        )


def test_each_kind_says_what_its_file_is():
    from partcad.assembly_factory_assy import AssemblyFactoryAssy
    from partcad.part_factory_3mf import PartFactory3mf
    from partcad.part_factory_step import PartFactoryStep
    from partcad.part_factory_stl import PartFactoryStl
    from partcad.sketch_factory_dxf import SketchFactoryDxf

    # Handed over as it is: PartCAD never opens the file itself.
    assert issubclass(PartFactoryStep, SourceFile) and not PartFactoryStep.TEMPLATE and not PartFactoryStep.BINARY
    assert issubclass(SketchFactoryDxf, SourceFile) and not SketchFactoryDxf.BINARY
    # Rendered as a template first.
    assert issubclass(AssemblyFactoryAssy, TemplateSourceFile)
    # Bytes, never opened as text.
    for factory_class in (PartFactory3mf, PartFactoryStl):
        assert issubclass(factory_class, BinarySourceFile) and factory_class.BINARY and not factory_class.TEMPLATE


def test_a_binary_file_is_never_read_to_be_rendered(tmp_path, monkeypatch):
    """'rendered_source' of a binary file does not even open it."""

    class Binary(BinarySourceFile):
        path = str(tmp_path / "drawing.dwg")
        name = "drawing"

    opened = []
    monkeypatch.setattr("builtins.open", lambda *args, **kwargs: opened.append(args) or (_ for _ in ()).throw(OSError))
    assert Binary().rendered_source() == str(tmp_path / "drawing.dwg")
    assert opened == []
