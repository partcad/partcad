#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the ASSY checker in ``partcad_utils.assy_lint``.

An ASSY file is a Jinja2 template, so the checker cannot simply parse it as
YAML. It masks the template first, which is what lets it keep the source line
and column of every finding -- and what forces it to stay quiet about anything
the mask made unknowable. Both halves are pinned here: real errors are found at
the right place, and templated files that are perfectly correct stay clean.
"""

import pytest

from partcad_utils.assy_lint import (
    ASSY_SCHEMA,
    CODE_SCHEMA,
    CODE_TEMPLATE,
    CODE_YAML,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    get_schema,
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


def test_the_tool_form_of_how_is_valid():
    """'holdWith'/'holdTo'/'driver' as tools, and the two ways a hold ends"""
    text = """
links:
  - part: plate
  - part: screw
    name: screw-tl
    connect:
      name: plate
      how:
        stage: snug
        turnTorqueMax: 0.4
        holdWith:
          //builtin:finger: [L, R]
        holdTo:
          //builtin:finger: []
        driver:
          //builtin:screwdriver-hex: [socket]
        holdUntil: screw-tr
  - part: screw
    name: screw-tr
    connect:
      name: plate
      how:
        stage: snug
        turnTorqueMax: 0.4
        # The other spellings: an interface pair for an ambiguous instance name,
        # a bare tool name for a driver, and a stage rather than a step.
        holdWith:
          //builtin:finger: [[//builtin:grip, L]]
        driver: //builtin:screwdriver-hex
        holdUntilStage: snug
"""
    assert check(text) == []


def test_the_older_spelling_of_hold_is_still_valid():
    """An interface name, or a list of them, with the tool left to the assembler"""
    text = """
links:
  - part: plate
  - part: screw
    connect:
      name: plate
      how:
        holdWith: m3-screw-6mm
        holdWithInstance: head
        holdTo: [grip, m3-thru]
"""
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


def test_only_assy_files_have_a_schema(tmp_path):
    # Reading the file, and deciding there is nothing to read it for, is the
    # caller's half of the job (`partcad_client.lint`); all this knows is which
    # names it has a schema for.
    assert schema_name_for_file("/pkg/logo.assy") == ASSY_SCHEMA
    assert schema_name_for_file("/pkg/LOGO.ASSY") == ASSY_SCHEMA
    assert schema_name_for_file("/pkg/partcad.yaml") is None
    assert schema_name_for_file("/pkg/notes.txt") is None


def test_the_schema_ships_with_the_package():
    schema = get_schema(ASSY_SCHEMA)
    assert schema["$schema"].startswith("http://json-schema.org/draft-07/")
    assert "node" in schema["definitions"]
