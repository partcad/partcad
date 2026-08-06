#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A declaration PartCAD cannot use costs the user that object, not the package.

Packages published against an older PartCAD can name features since retired -
the 'ai-cadquery'/'ai-build123d' part types are the ones in the wild. Loading such
a package used to drop every affected object with only a log line, abort the
enumeration loop at the first one (taking the objects declared after it with it),
and raise a bare KeyError at anyone who then asked for one by name.
"""

import os

import pytest
import yaml

import partcad as pc
from partcad import factory


@pytest.fixture
def package(tmp_path):
    """A package with a usable part on each side of an unusable one.

    The ordering is the point: the good part declared *after* the bad one is
    what proves the enumeration no longer stops at the first failure.
    """
    config = {
        "name": "//test",
        "parts": {
            "good_before": {"type": "cadquery", "path": "cube.py"},
            "obsolete": {"type": "ai-cadquery", "provider": "openai", "desc": "x" * 5000},
            "good_after": {"type": "cadquery", "path": "cube.py"},
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "cube.py").write_text(
        "import cadquery as cq\nshape = cq.Workplane('front').box(1, 1, 1)\nshow_object(shape)\n"
    )
    return tmp_path


def test_an_unusable_declaration_does_not_hide_the_rest(package):
    ctx = pc.Context(str(package))
    project = ctx.get_project("//")

    assert sorted(project.parts.keys()) == ["good_after", "good_before"]
    # The one that could not be created is remembered rather than forgotten.
    assert list(project.broken_objects["part"]) == ["obsolete"]


def test_the_recorded_reason_names_the_type(package):
    ctx = pc.Context(str(package))
    project = ctx.get_project("//")

    reason = project.get_broken_object_reason("part", "obsolete")
    assert "ai-cadquery" in reason
    assert "obsolete" in reason
    # Short enough to read: these declarations carry multi-page descriptions, and
    # logging the whole configuration buried every other message.
    assert len(reason) < 400
    assert "\n" not in reason


def test_getting_an_unusable_object_returns_none_rather_than_raising(package):
    ctx = pc.Context(str(package))

    # A bare KeyError used to come out of here - from the very branch that had
    # just logged "Failed to instantiate a non-parametrized object".
    assert ctx.get_part("//:obsolete") is None
    # ...and the usable ones still resolve.
    assert ctx.get_part("//:good_after") is not None


def test_getting_an_object_that_was_never_declared_still_returns_none(package):
    ctx = pc.Context(str(package))
    assert ctx.get_part("//:no_such_part") is None


def test_unknown_type_exception_lists_what_is_supported():
    with pytest.raises(factory.UnknownTypeException) as excinfo:
        factory.instantiate("part", "ai-cadquery", None, None, None, {"name": "some_part"})

    message = str(excinfo.value)
    assert "ai-cadquery" in message
    assert "some_part" in message
    # The supported types are listed, because "unknown type" on its own leaves
    # the user with nothing to do about it.
    assert "cadquery" in message
    assert excinfo.value.kind == "part"
    assert excinfo.value.type == "ai-cadquery"


def test_a_parametrized_instance_of_an_unusable_declaration_returns_none(tmp_path):
    """The parameterized branch of get_object() degrades the same way.

    It reaches 'factory.instantiate' by a different path than the plain one, and
    used to report "Failed to instantiate parameterized object" and then hand
    back whatever was (not) in the dict. The base has to *declare* the parameter
    for the lookup to get that far; without that it is rejected earlier, as an
    unknown parameter.
    """
    config = {
        "name": "//test",
        "parts": {
            "obsolete": {
                "type": "ai-cadquery",
                "provider": "openai",
                "desc": "x" * 100,
                "parameters": {"width": {"type": "float", "default": 1.0}},
            }
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    ctx = pc.Context(str(tmp_path))

    assert ctx.get_part("//:obsolete;width=5") is None

    # Recorded under the *parameterized* name, which is what proves the
    # parameterized branch reported it rather than the plain one.
    project = ctx.get_project("//")
    assert "obsolete;width=5" in project.broken_objects["part"]
    assert "ai-cadquery" in project.get_broken_object_reason("part", "obsolete;width=5")


def test_record_broken_object_shortens_and_flattens_the_reason(tmp_path):
    """Reasons go in a log line and a tree row, so they are one short line.

    These declarations embed multi-page descriptions; logging the configuration
    whole is what buried every other message.
    """
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test"}))
    project = pc.Context(str(tmp_path)).get_project("//")

    project.record_broken_object("part", "noisy", Exception("line one\nline two   spaced\n" + "x" * 5000))

    reason = project.get_broken_object_reason("part", "noisy")
    assert "\n" not in reason
    assert "line one line two spaced" in reason
    assert len(reason) <= 200
    assert reason.endswith("...")


def test_record_broken_object_reraises_a_needs_update_exception(tmp_path):
    """ "This package needs a newer PartCAD" is not one object's problem.

    Filing it against a single object would swallow the caller's "update
    PartCAD" prompt.
    """
    from partcad.exception import NeedsUpdateException

    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test"}))
    project = pc.Context(str(tmp_path)).get_project("//")

    with pytest.raises(NeedsUpdateException):
        project.record_broken_object("part", "whatever", NeedsUpdateException("too old"))

    assert project.get_broken_object_reason("part", "whatever") is None


def test_an_exception_with_no_message_still_records_something(tmp_path):
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump({"name": "//test"}))
    project = pc.Context(str(tmp_path)).get_project("//")

    project.record_broken_object("part", "silent", ValueError())

    assert project.get_broken_object_reason("part", "silent") == "ValueError"


def test_a_factory_that_produces_nothing_is_recorded_rather_than_indexed(tmp_path):
    """A factory can construct without registering an object, and used to crash.

    This is the other half of the KeyError: the type is known, so nothing raises,
    but the object never lands in the dict. The branch that noticed this then
    indexed the dict it had just found the name to be missing from.
    """
    config = {"name": "//test", "parts": {"silent": {"type": "test-silent"}}}
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))

    class SilentFactory:
        def __init__(self, ctx, source_project, target_project, config):
            pass  # Constructs, registers nothing.

    saved = factory.all["part"].get("test-silent")
    factory.register("part", "test-silent", SilentFactory)
    try:
        ctx = pc.Context(str(tmp_path))
        assert ctx.get_part("//:silent") is None

        project = ctx.get_project("//")
        assert "produced no object" in project.get_broken_object_reason("part", "silent")
    finally:
        if saved is None:
            del factory.all["part"]["test-silent"]
        else:
            factory.register("part", "test-silent", saved)
