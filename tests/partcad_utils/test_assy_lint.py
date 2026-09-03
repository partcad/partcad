#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the YAML checker in ``partcad_utils.assy_lint``.

An ASSY file and a ``partcad.yaml`` are both Jinja2 templates, so the checker
cannot simply parse either as YAML. It masks the template first, which is what
lets it keep the source line and column of every finding -- and what forces it
to stay quiet about anything the mask made unknowable. Both halves are pinned
here: real errors are found at the right place, and templated files that are
perfectly correct stay clean.

Most of what follows uses ASSY files, because the two documents differ only in
which schema governs them; the block at the end covers what is specific to a
package configuration.
"""

import pytest

from partcad_utils.assy_lint import (
    ASSY_SCHEMA,
    CODE_SCHEMA,
    CODE_TEMPLATE,
    CODE_YAML,
    FLAVOR_SCENE,
    PARTCAD_SCHEMA,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    get_schema,
    is_assy_file,
    schema_for_file,
    schema_name_for_file,
    validate_source,
)


def check(text):
    return validate_source(text, get_schema(ASSY_SCHEMA))


def only(text):
    diagnostics = check(text)
    assert len(diagnostics) == 1, "expected exactly one finding, got %r" % (diagnostics,)
    return diagnostics[0]


# ---- files that must stay clean --------------------------------------------


@pytest.mark.parametrize(
    "text",
    [
        # Plain, untemplated.
        "links:\n  - part: cube\n    location: [[0, 0, 0], [0, 0, 1], 0]\n",
        # A parameter inside an OCCT location: the schema wants numbers there,
        # and the filler standing in for the expression is not one.
        "links:\n  - part: cube\n    location: [[0, 0, {{ param_offset }}], [0, 0, 1], 0]\n",
        # A whole value, and a value built by concatenation.
        "name: {{ name }}_head\nlinks:\n  - part: {{ param_part }}\n",
        # A templated property name.
        "links:\n  - part: cube\n    params:\n      {{ pname }}: 5\n",
        # Control flow: the loop body is checked once, the tag lines vanish.
        "links:\n  {% for x in [0, 1] %}\n  - part: cube\n  {% endfor %}\n",
        # Both branches of a conditional survive masking and both are valid.
        "links:\n  {% if x %}\n  - part: a\n  {% else %}\n  - part: b\n  {% endif %}\n",
        # Assignments and comments.
        "{% set side = 'L' %}\n{# a comment #}\nlinks:\n  - part: cube\n    name: {{ side }}\n",
        # An empty file renders to nothing, which is not an error to type.
        "",
        "{% set unused = 1 %}\n",
    ],
)
def test_valid_sources_report_nothing(text):
    assert check(text) == []


def test_examples_shipped_with_partcad_are_clean(tmp_path):
    # The nesting, `connect:` and multi-level `links:` of a real file, in one go.
    text = """
name: bracket
description: an example
links:
  - part: example-bracket
  - part: example-motor
    package: //pub/std
    connect:
      with: nema-17-motor-mount
      name: example-bracket
      toInstance: "{{ param_placement }}"
      toPort: "*{{ param_port }}*"
      toParams: {offset: -15}
  - links:
      - assembly: sub
        location: [[0, 0, 2.5], [0, 0, 1], 0]
        params:
          length: {{ param_length }}
    name: head
"""
    assert check(text) == []


# ---- template errors -------------------------------------------------------


def test_unclosed_block_is_reported_on_its_own_line():
    diagnostic = only("links:\n  {% for x in [1, 2] %}\n  - part: cube\n")
    assert diagnostic.severity == SEVERITY_ERROR
    assert diagnostic.code == CODE_TEMPLATE
    assert "endfor" in diagnostic.message
    # Jinja2 blames the line the unclosed block was opened on (zero-based).
    assert diagnostic.line == 1


def test_unterminated_expression_is_a_template_error():
    diagnostic = only("links:\n  - part: {{ oops\n")
    assert diagnostic.code == CODE_TEMPLATE


def test_a_broken_template_suppresses_the_yaml_pass():
    # Every finding is the template one: a template that does not parse renders
    # to nothing, so follow-on YAML complaints would be noise.
    assert all(d.code == CODE_TEMPLATE for d in check("links:\n  {% for %}\n   - part: a\n"))


# ---- YAML errors -----------------------------------------------------------


def test_yaml_error_carries_the_source_position():
    diagnostic = only("links:\n  - part: cube\n   name: bad\n")
    assert diagnostic.severity == SEVERITY_ERROR
    assert diagnostic.code == CODE_YAML
    assert diagnostic.line == 2


def test_yaml_error_on_a_templated_line_is_only_a_warning():
    # `x: {% if c %}a{% else %}b{% endif %}` masks to both branches side by
    # side. That is a limitation of the mask, not a mistake by the user.
    diagnostic = only("links:\n  - part: cube\n    params: {% if c %}{a: 1}{% else %}{b: 2}{% endif %}\n")
    assert diagnostic.severity == SEVERITY_WARNING
    assert diagnostic.code == CODE_YAML


# ---- schema violations -----------------------------------------------------


def test_misspelled_property_points_at_the_key():
    diagnostic = only("links:\n  - part: cube\n    locaton: [[0, 0, 0], [0, 0, 1], 0]\n")
    assert diagnostic.severity == SEVERITY_WARNING
    assert diagnostic.code == CODE_SCHEMA
    assert "locaton" in diagnostic.message
    assert (diagnostic.line, diagnostic.column) == (2, 4)


def test_misspelled_property_of_a_nested_object():
    diagnostic = only("links:\n  - part: cube\n    connect:\n      name: other\n      toInstanse: X\n")
    assert "toInstanse" in diagnostic.message
    assert (diagnostic.line, diagnostic.column) == (4, 6)


def test_location_that_is_not_an_occt_location():
    diagnostics = check("links:\n  - part: cube\n    location: [0, 0, 0]\n")
    assert diagnostics
    assert all(d.severity == SEVERITY_ERROR and d.code == CODE_SCHEMA for d in diagnostics)
    assert all(d.line == 2 for d in diagnostics)


@pytest.mark.parametrize(
    "text,names",
    [
        ("links:\n  - part: cube\n    assembly: other\n", ("part", "assembly")),
        (
            "links:\n  - part: cube\n    location: [[0, 0, 0], [0, 0, 1], 0]\n    connect:\n      name: other\n",
            ("location", "connect"),
        ),
    ],
)
def test_mutually_exclusive_keys(text, names):
    diagnostic = only(text)
    assert diagnostic.severity == SEVERITY_ERROR
    for name in names:
        assert ("'%s'" % name) in diagnostic.message
    assert "mutually exclusive" in diagnostic.message


def test_node_that_places_nothing():
    diagnostic = only("links:\n  - name: nothing\n")
    assert "at least one of" in diagnostic.message
    assert diagnostic.line == 1


def test_a_conditional_inside_a_node_silences_the_key_level_checks():
    # Masking keeps both branches, so the node ends up with `part:` and
    # `assembly:` at once. Only one of them is ever really there, so the
    # mutually-exclusive check has to stand down inside a conditional.
    text = """
links:
  - name: maybe
    {% if c %}
    part: cube
    {% else %}
    assembly: sub
    {% endif %}
"""
    assert check(text) == []


def test_the_same_clash_without_a_conditional_is_reported():
    # The counterpart of the test above: nothing is masked, so nothing excuses
    # the clash.
    diagnostic = only("links:\n  - name: maybe\n    part: cube\n    assembly: sub\n")
    assert "mutually exclusive" in diagnostic.message


def test_a_loop_around_a_node_does_not_silence_its_checks():
    # The `{% for %}` lines are outside the node they repeat, so a real clash
    # inside the body is still reported.
    text = """
links:
  {% for x in [0, 1] %}
  - part: cube
    assembly: sub
  {% endfor %}
"""
    diagnostic = only(text)
    assert "mutually exclusive" in diagnostic.message


def test_findings_are_ordered_by_position():
    diagnostics = check("links:\n  - part: a\n    bogus1: 1\n  - part: b\n    bogus2: 2\n")
    assert [d.line for d in diagnostics] == [2, 4]


# ---- entry points ----------------------------------------------------------


def test_diagnostic_dict_is_json_rpc_shaped():
    payload = only("links:\n  - part: cube\n    locaton: 1\n").to_dict()
    assert payload["severity"] == SEVERITY_WARNING
    assert payload["source"] == "partcad"
    assert payload["line"] == 2 and payload["column"] == 4
    assert payload["endLine"] >= payload["line"]


def test_each_kind_of_file_finds_its_schema(tmp_path):
    # Reading the file, and deciding there is nothing to read it for, is the
    # caller's half of the job (`partcad_client.lint`); all this knows is which
    # names it has a schema for.
    assert schema_name_for_file("/pkg/logo.assy") == ASSY_SCHEMA
    assert schema_name_for_file("/pkg/LOGO.ASSY") == ASSY_SCHEMA
    assert schema_name_for_file("/pkg/partcad.yaml") == PARTCAD_SCHEMA
    assert schema_name_for_file("/pkg/PartCAD.YAML") == PARTCAD_SCHEMA
    # A configuration is recognised by its whole name, so a '.yaml' beside it is
    # somebody's own file rather than a package this has an opinion about.
    assert schema_name_for_file("/pkg/parts.yaml") is None
    assert schema_name_for_file("/pkg/notes.txt") is None


def test_only_an_assy_file_has_a_flavor():
    """A `partcad.yaml` is not read as an assembly or as a scene; it is read."""
    assert is_assy_file("/pkg/logo.assy")
    assert not is_assy_file("/pkg/partcad.yaml")
    assert not is_assy_file("/pkg/notes.txt")


def test_the_scene_flavor_does_not_reach_a_configuration():
    """`--schema scene` on a `partcad.yaml` gets the configuration schema.

    Deriving one would forbid a `how` no package configuration has, and hand a
    caller that sends the same parameters for every document a schema nothing
    is checked against.
    """
    assert schema_for_file("/pkg/partcad.yaml", FLAVOR_SCENE) is get_schema(PARTCAD_SCHEMA)
    assert schema_for_file("/pkg/logo.assy", FLAVOR_SCENE) is not get_schema(ASSY_SCHEMA)


def test_the_schemas_ship_with_the_package():
    schema = get_schema(ASSY_SCHEMA)
    assert schema["$schema"].startswith("http://json-schema.org/draft-07/")
    assert "node" in schema["definitions"]

    schema = get_schema(PARTCAD_SCHEMA)
    assert schema["$schema"].startswith("http://json-schema.org/draft-07/")
    assert "parts" in schema["properties"]


# A package configuration is the same kind of document as an ASSY file -- a
# Jinja2 template that renders to YAML and then has to match a schema -- so the
# whole of the machinery above applies to it. What follows is what is specific
# to it: which findings it produces, and what it must not produce a finding for.


def config_diagnostics(text):
    return validate_source(text, get_schema(PARTCAD_SCHEMA))


def test_a_configuration_is_checked_against_the_configuration_schema():
    """A part type PartCAD has no factory for, reported at the declaration."""
    diagnostics = config_diagnostics("parts:\n  cube:\n    type: nonsense\n")
    assert [(d.severity, d.code, d.path) for d in diagnostics] == [(SEVERITY_ERROR, CODE_SCHEMA, "$.parts.cube")]
    assert diagnostics[0].line == 2


def test_a_misspelled_configuration_key_is_a_warning_at_the_key():
    diagnostics = config_diagnostics("desc: a package\nfoo: bar\n")
    assert len(diagnostics) == 1
    assert diagnostics[0].severity == SEVERITY_WARNING
    assert diagnostics[0].message == "unexpected property 'foo'"
    assert (diagnostics[0].line, diagnostics[0].column) == (1, 0)


def test_a_freshly_initialized_package_is_clean():
    """What `pc init` writes, and `pc add part` leaves beside a populated one.

    An empty section parses as null, which is how the loader reads it too
    ('config_obj.get(section) or {}'). A schema that rejected it would put three
    errors on every new package the moment its configuration was opened.
    """
    assert config_diagnostics("sketches:\nparts:\nassemblies:\ndependencies:\n") == []
    assert config_diagnostics("sketches:\nparts:\n  cube:\n    type: cadquery\nassemblies:\n") == []


def test_jinja2_in_a_configuration_is_not_mistaken_for_broken_yaml():
    """`partcad.yaml` is rendered as a template too, `includePaths` and all."""
    assert (
        config_diagnostics(
            "parts:\n"
            "{% for size in [10, 20] %}\n"
            "  cube_{{ size }}:\n"
            "    type: cadquery\n"
            "    path: cube.py\n"
            "{% endfor %}\n"
        )
        == []
    )
