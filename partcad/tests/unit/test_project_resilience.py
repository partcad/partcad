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


# A type PartCAD itself retired is not the same as a type nobody ever had.
#
# The public index is a separate repository, and it still declares the
# generative-AI part types removed in 0.7.153. Reporting those as errors makes
# every command that so much as walks the index exit non-zero, over declarations
# the user cannot edit and cannot fix. Reporting a genuine typo as anything less
# than an error would be worse, so the two have to stay apart.


def _record_warnings(monkeypatch):
    """Collect pc_logging.warning() calls.

    The 'partcad' logger sets propagate=False, so the caplog fixture (which
    attaches to the root logger) sees nothing on the pytest version used in CI.
    """
    recorded = []
    monkeypatch.setattr(pc.logging, "warning", lambda *args, **kwargs: recorded.append(" ".join(str(a) for a in args)))
    return recorded


@pytest.fixture
def unknown_type_package(tmp_path):
    """The same package, but the unusable type is a typo rather than a retirement."""
    config = {
        "name": "//test",
        "parts": {
            "good_before": {"type": "cadquery", "path": "cube.py"},
            "typo": {"type": "nonsense"},
            "good_after": {"type": "cadquery", "path": "cube.py"},
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    (tmp_path / "cube.py").write_text("import cadquery as cq\nshow_object(cq.Workplane('front').box(1, 1, 1))\n")
    return tmp_path


def test_the_retired_types_are_the_ones_that_were_removed():
    """The set is closed, and comes from what #486 actually deleted.

    Those four are the 'part_factory_ai_*' modules that PR removed along with
    their 'factory.register()' calls. Anything else added here would quietly
    downgrade a real error.
    """
    assert set(factory.RETIRED_TYPES) == {"ai-build123d", "ai-cadquery", "ai-openscad", "ai-sdf"}
    assert set(factory.RETIRED_TYPES.values()) == {"0.7.153"}
    # And none of them is registered, which is what makes them retired.
    for kind in factory.all:
        assert not set(factory.RETIRED_TYPES) & set(factory.all[kind])


def test_a_retired_type_does_not_make_the_command_fail(package):
    """pc_logging.error() sets the flag the CLI turns into a non-zero exit code.

    This is the whole point: 'pc list -r //pub/examples' walked the index, hit
    the retired declarations it carries, and aborted on them.
    """
    pc.logging.reset_errors()

    ctx = pc.Context(str(package))
    project = ctx.get_project("//")

    assert pc.logging.had_errors is False
    # Still skipped, and still recorded as broken - only the severity changed.
    assert sorted(project.parts.keys()) == ["good_after", "good_before"]
    assert list(project.broken_objects["part"]) == ["obsolete"]


def test_a_retired_type_says_it_was_retired_and_when(package, monkeypatch):
    recorded = _record_warnings(monkeypatch)

    project = pc.Context(str(package)).get_project("//")

    reason = project.get_broken_object_reason("part", "obsolete")
    assert "retired in PartCAD 0.7.153" in reason
    assert "ai-cadquery" in reason
    assert any("ai-cadquery" in message and "retired" in message for message in recorded), recorded


def test_a_retired_type_raises_a_retired_type_exception():
    with pytest.raises(factory.RetiredTypeException) as excinfo:
        factory.instantiate("part", "ai-openscad", None, None, None, {"name": "some_part"})

    # Still an unknown type, so every caller that handles those keeps working.
    assert isinstance(excinfo.value, factory.UnknownTypeException)
    assert excinfo.value.release == "0.7.153"
    assert "retired" in str(excinfo.value)
    assert "some_part" in str(excinfo.value)


def test_an_unknown_type_is_still_an_error(unknown_type_package):
    """The property that must not regress along with the above.

    A type nobody retired is a mistake in the package being loaded, and it has
    to keep failing the command that found it.
    """
    pc.logging.reset_errors()

    project = pc.Context(str(unknown_type_package)).get_project("//")

    assert pc.logging.had_errors is True
    reason = project.get_broken_object_reason("part", "typo")
    assert "unknown part type 'nonsense'" in reason
    assert "retired" not in reason
    # ...and it costs the caller that one object, exactly as before.
    assert sorted(project.parts.keys()) == ["good_after", "good_before"]


def test_an_unknown_type_is_reported_at_error_level(unknown_type_package, monkeypatch):
    recorded = _record_warnings(monkeypatch)

    pc.Context(str(unknown_type_package)).get_project("//")

    assert not any("nonsense" in message for message in recorded), recorded


# ...and the retirement is scoped to the kind that was actually retired.
#
# Every 'ai-*' registration #486 removed was a 'factory.register("part", ...)';
# there never was an 'ai-cadquery' sketch, assembly, provider or repository. So
# the name only means "retired" on a part. Anywhere else it is a typo in a
# package somebody can fix, and forgiving it would both hide that and claim a
# release had a type it never had.


@pytest.fixture
def retired_part_type_on_a_sketch_package(tmp_path):
    """A sketch declared with a type only ever registered for parts."""
    config = {
        "name": "//test",
        "sketches": {"not_a_sketch_type": {"type": "ai-cadquery"}},
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(config))
    return tmp_path


def test_a_retired_part_type_on_a_sketch_is_unknown_rather_than_retired(
    retired_part_type_on_a_sketch_package,
):
    """It has to fail the command, exactly as any other unknown sketch type does."""
    pc.logging.reset_errors()

    project = pc.Context(str(retired_part_type_on_a_sketch_package)).get_project("//")

    assert pc.logging.had_errors is True
    reason = project.get_broken_object_reason("sketch", "not_a_sketch_type")
    assert "unknown sketch type 'ai-cadquery'" in reason
    # And it must not claim a release that never had such a sketch type.
    assert "retired" not in reason
    assert "0.7.153" not in reason


def test_a_retired_part_type_on_a_sketch_is_not_reported_as_a_warning(
    retired_part_type_on_a_sketch_package, monkeypatch
):
    recorded = _record_warnings(monkeypatch)

    pc.Context(str(retired_part_type_on_a_sketch_package)).get_project("//")

    assert not any("ai-cadquery" in message for message in recorded), recorded


@pytest.mark.parametrize("kind", ["sketch", "assembly", "provider", "repository"])
def test_a_retired_part_type_raises_a_plain_unknown_type_for_other_kinds(kind):
    with pytest.raises(factory.UnknownTypeException) as excinfo:
        factory.instantiate(kind, "ai-cadquery", None, None, None, {"name": "some_object"})

    assert not isinstance(excinfo.value, factory.RetiredTypeException)
    assert "unknown %s type 'ai-cadquery'" % kind in str(excinfo.value)


def test_a_retired_part_type_is_still_retired_on_a_part():
    """The guard above must not have cost the case the retirement is for."""
    with pytest.raises(factory.RetiredTypeException):
        factory.instantiate("part", "ai-cadquery", None, None, None, {"name": "some_part"})
