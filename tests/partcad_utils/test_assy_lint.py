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
    CODE_LINKS,
    CODE_MANUFACTURABLE,
    CODE_SCHEMA,
    CODE_TEMPLATE,
    CODE_YAML,
    FLAVOR_SCENE,
    PARTCAD_SCHEMA,
    SEVERITY_ERROR,
    SEVERITY_WARNING,
    Render,
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
        # An expression alone on its line stands for lines of YAML, or for none:
        # here, a call to an undefined function that stops rendering with a
        # message, which once made the next key "mapping values are not allowed
        # here".
        "{% if param_width < 12 %}\n{{ width_must_be_at_least_12_in() }}\n{% endif %}\nlinks:\n  - part: cube\n",
        # A macro: its body renders nothing where it is defined, and each call
        # on a line of its own renders items.
        "{% macro leg(x) %}\n  - part: leg\n    location: [[{{ x }}, 0, 0], [0, 0, 1], 0]\n{% endmacro %}\n"
        "links:\n{{ leg(0) }}\n{{ leg(10) }}\n",
        "{% set legs %}\n  - part: leg\n{% endset %}\nlinks:\n{{ legs }}\n",
        "{% macro named() %}cube{% endmacro %}\nlinks:\n{% call named() %}{% endcall %}\n",
        # Items that come from another file.
        "links:\n{% include 'legs.assy' %}\n",
        # A value written on the line after its key.
        "links:\n  - part:\n      {{ param_part }}\n",
    ],
)
def test_valid_sources_report_nothing(text):
    assert check(text) == []


@pytest.mark.parametrize(
    "text, line",
    [
        ("{{ check() }}\nlinks:\n  - part: cube\n    assembly: sub\n", 2),
        ("{% macro leg() %}\n  - part: leg\n{% endmacro %}\nlinks:\n{{ leg() }}\n  - part: a\n    assembly: b\n", 5),
    ],
)
def test_lines_a_template_renders_do_not_excuse_the_yaml_beside_them(text, line):
    diagnostic = only(text)
    assert "mutually exclusive" in diagnostic.message
    assert diagnostic.line == line


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
    # The link the 'connect:' names is placed above it, so the misspelling is
    # the only thing wrong with the document: a 'connect:' to a link nothing
    # places is a finding of its own (see 'check_links' below).
    diagnostic = only("links:\n  - part: other\n  - part: cube\n    connect:\n      name: other\n      toInstanse: X\n")
    assert "toInstanse" in diagnostic.message
    assert (diagnostic.line, diagnostic.column) == (5, 6)


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
            # 'other' is placed above, so the clash is the only finding; see
            # 'test_misspelled_property_of_a_nested_object'.
            "links:\n"
            "  - part: other\n"
            "  - part: cube\n"
            "    location: [[0, 0, 0], [0, 0, 1], 0]\n"
            "    connect:\n"
            "      name: other\n",
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


@pytest.mark.parametrize(
    "declaration",
    [
        "parameters:\n      - moveX\n      - moveY\n      - turnZ\n",  # the oldest spelling there is
        "parameters:\n      - move-x\n      - turn-z\n",  # and its hyphenated form
        "parameters:\n      moveZ: [0, 10, 0]\n",
        "parameters:\n      size: 3.0\n",
    ],
)
def test_the_linter_accepts_every_way_an_interface_declares_parameters(declaration):
    """What the loader accepts, `pc lint` has to accept.

    The bare list is the one this nearly lost: the loader was fixed to expand it
    and the schema went on refusing it, so a package that has used the form since
    interfaces existed loaded fine and failed its own linter.
    """
    source = "interfaces:\n  iface:\n    desc: an interface\n    %s" % declaration
    assert validate_source(source, get_schema(PARTCAD_SCHEMA)) == []


@pytest.mark.parametrize(
    "declaration",
    [
        "threadStep: 0.7\n",
        'threadStep: "%pitch%"\n    parameters:\n      pitch: 0.7\n',
        "selfScrew: true\n",
        "multiConnect: true\n",
        "multiConnect: false\n",
    ],
)
def test_the_linter_accepts_what_an_interface_says_about_connecting_through_it(declaration):
    """The other half of the same rule, for what an interface says about a connection.

    'multiConnect' is the one this was written for. 'Interface' has read it since
    it was added and hands it down a family through '_inherited', and the schema -
    whose interface body is 'additionalProperties: false' - never listed it. So a
    package could declare it and work, and failed its own 'pc lint' the moment
    anybody ran one; the only packages it did not break were those that never did.
    """
    source = "interfaces:\n  iface:\n    desc: an interface\n    %s" % declaration
    assert validate_source(source, get_schema(PARTCAD_SCHEMA)) == []


def test_the_linter_still_wants_a_direction_for_a_name_it_does_not_know():
    """The other half of the same rule: only those six may be named bare."""
    source = "interfaces:\n  iface:\n    desc: an interface\n    parameters:\n      - slideAlongTheRail\n"
    assert validate_source(source, get_schema(PARTCAD_SCHEMA)) != []


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


@pytest.mark.parametrize(
    "section,body",
    [
        ("parts", "    type: build123d\n"),
        ("assemblies", "    type: assy\n"),
        ("sketches", "    type: build123d\n"),
        ("interfaces", "    abstract: true\n"),
    ],
)
def test_an_object_may_name_the_images_it_was_modeled_from(section, body):
    """`images:` is what puts a drawing beside an object in the README.

    `Project.generate_readme()` renders that list for every kind of object it
    writes a section for, so all four of them accept it -- a key the renderer
    reads and the schema rejected is one nobody could write down.
    """
    assert (
        config_diagnostics("%s:\n  bracket:\n%s    images:\n      - drawing.png\n      - photo.jpg\n" % (section, body))
        == []
    )


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


# ---- links that nothing places ---------------------------------------------
#
# A relation between two parts of one document, which no schema can describe: a
# 'connect:' says which link already in the assembly this one is placed against,
# and a name that is wrong is answered, much later and much further away, with
# "Target part not found" and a part at the origin. See 'check_links'.


def link_findings(text):
    return [diagnostic for diagnostic in check(text) if diagnostic.code == CODE_LINKS]


def one_link_finding(text):
    found = link_findings(text)
    assert len(found) == 1, "expected exactly one finding, got %r" % (found,)
    return found[0]


CHAIN = "links:\n  - part: a\n    name: first\n  - part: b\n    name: second\n"


def test_a_connect_to_a_preceding_sibling_is_clean():
    assert link_findings(CHAIN + "  - part: c\n    connectPorts:\n      name: first\n") == []


def test_a_connect_to_a_link_nothing_places():
    finding = one_link_finding(CHAIN + "  - part: c\n    connectPorts:\n      name: third\n")
    assert "third" in finding.message
    assert finding.severity == SEVERITY_ERROR
    # On the name itself, not on the node: that is the character to fix.
    assert finding.line == 7


def test_a_connect_to_a_link_placed_later_says_so():
    # The factory looks for the target among the children placed so far, so a
    # link written below this one is not there yet -- which is a different
    # mistake from a misspelling and reads differently.
    text = "links:\n  - part: a\n    connectPorts:\n      name: later\n  - part: b\n    name: later\n"
    assert "after this node" in one_link_finding(text).message


def test_a_connect_across_two_links_lists_says_so():
    text = (
        "links:\n"
        "  - name: frame\n"
        "    links:\n"
        "      - part: a\n"
        "        name: inner\n"
        "  - part: b\n"
        "    connectPorts:\n"
        "      name: inner\n"
    )
    assert "same 'links:' list" in one_link_finding(text).message


def test_a_connect_that_names_no_link_at_all():
    assert "needs a 'name'" in one_link_finding(CHAIN + "  - part: c\n    connect: {}\n").message


def test_interferes_may_name_a_link_anywhere_in_the_file():
    # A connection joins two items; a screw driven through them passes through
    # more, and 'interferes' names those. They are matched by name across the
    # assemblies a file embeds, so the whole document is the scope.
    text = (
        "links:\n"
        "  - name: frame\n"
        "    links:\n"
        "      - part: a\n"
        "        name: inner\n"
        "  - part: b\n"
        "    name: screw\n"
        "    connect:\n"
        "      name: frame\n"
        "      interferes: [inner]\n"
    )
    assert link_findings(text) == []


def test_interferes_that_names_nothing():
    text = CHAIN + "  - part: c\n    connect:\n      name: first\n      interferes: [second, nosuch]\n"
    assert "nosuch" in one_link_finding(text).message


def test_the_root_node_has_nothing_to_connect_to():
    # Reported here as well as when the file is read, where
    # 'apply_root_placement' says the same thing: the root node *is* the
    # assembly, so it has no sibling.
    assert "nothing to 'connect' to" in one_link_finding("connect:\n  name: x\nlinks:\n  - part: a\n").message


def test_a_node_is_addressed_by_what_it_places_when_it_has_no_name():
    assert link_findings("links:\n  - part: cube\n  - part: b\n    connectPorts:\n      name: cube\n") == []


def test_a_templated_name_silences_the_check():
    # Which link a template places is only known once it has been rendered, and
    # a finding that depends on what the mask hid is dropped rather than
    # reported: an editor that underlines correct code is worse than one that
    # misses something.
    text = "links:\n  - part: a\n    name: {{ which }}\n  - part: b\n    connectPorts:\n      name: {{ which }}\n"
    assert link_findings(text) == []


def test_a_loop_around_the_links_silences_the_check():
    text = (
        "links:\n"
        "{% for n in [1, 2] %}\n"
        "  - part: a\n"
        "    name: plate_{{ n }}\n"
        "{% endfor %}\n"
        "  - part: b\n"
        "    connectPorts:\n"
        "      name: plate_1\n"
    )
    assert link_findings(text) == []


def test_a_scene_connect_is_checked_the_same_way():
    # A scene states where things are, and it says so with the same 'connect:'
    # an assembly uses; only 'how' is forbidden there.
    found = validate_source(
        CHAIN + "  - part: c\n    connectPorts:\n      name: third\n",
        schema_for_file("bench.assy", FLAVOR_SCENE),
    )
    assert [one.message for one in found if one.code == CODE_LINKS] == [
        "nothing in this file places a link called 'third'"
    ]


def test_a_configuration_has_no_links_to_check():
    assert [one for one in config_diagnostics("parts:\n  cube:\n    type: cadquery\n") if one.code == CODE_LINKS] == []


# ---- checked as it renders --------------------------------------------------
#
# What PartCAD reads is the rendering: the items a loop produces, the branch an
# '{% if %}' takes, the numbers expressions come to. Wherever the values a file
# is rendered with are known, that is what is checked, and each finding is put
# back on the template line it came from.


def rendered(text, variables=None, schema=ASSY_SCHEMA, **kwargs):
    return validate_source(text, get_schema(schema), renders=[Render(variables or {})], **kwargs)


def test_a_value_an_expression_computes_is_checked():
    # Masked, the filler standing in for the expression excused the value. As
    # rendered, the location is a string and the schema says where.
    text = "links:\n  - part: cube\n    location: {{ where }}\n"
    diagnostic = rendered(text, {"where": "'up'"})[0]
    assert diagnostic.code == CODE_SCHEMA
    assert (diagnostic.line, diagnostic.column) == (2, text.split("\n")[2].index("{{"))
    assert rendered(text, {"where": "[[0, 0, 1], [0, 0, 1], 0]"}) == []


def test_a_finding_in_a_loop_is_reported_once_at_the_body():
    text = "links:\n{% for n in range(3) %}\n  - part: a\n    locaton: {{ n }}\n{% endfor %}\n"
    diagnostics = rendered(text)
    assert [(d.message, d.line, d.column) for d in diagnostics] == [("unexpected property 'locaton'", 3, 4)]


def test_only_the_branch_that_renders_is_checked():
    # Masked, both branches survive side by side, which is not YAML at all.
    text = "links:\n{%- if subject %}\n  - part: cube\n{%- else %}\n  []\n{%- endif %}\n"
    assert rendered(text, {"subject": True}) == []
    assert rendered(text, {"subject": False}) == []


def test_yaml_an_expression_breaks_is_reported_at_the_expression():
    text = "links:\n  - part: cube\n    name: {{ label }}\n"
    diagnostic = only_of(rendered(text, {"label": "a: b"}))
    assert diagnostic.code == CODE_YAML
    assert (diagnostic.line, diagnostic.column) == (2, text.split("\n")[2].index("{{"))


def test_a_template_that_raises_with_its_defaults_is_an_error_on_that_line():
    text = "{% if width < 12 %}\n{{ width_must_be_at_least_12() }}\n{% endif %}\nlinks:\n  - part: cube\n"
    assert rendered(text, {"width": 20}) == []
    diagnostic = only_of(validate_source(text, get_schema(ASSY_SCHEMA), renders=[Render({"width": 6}, label="desk")]))
    assert diagnostic.code == CODE_TEMPLATE
    assert diagnostic.line == 1
    assert "'desk'" in diagnostic.message and "width_must_be_at_least_12" in diagnostic.message


def test_every_declaration_s_rendering_is_checked():
    text = "links:\n{% for n in range(count) %}\n  - part: a\n{% endfor %}\n"
    schema = get_schema(ASSY_SCHEMA)
    ok, broken = Render({"count": 1}), Render({"count": "x"}, label="broken")
    assert validate_source(text, schema, renders=[ok]) == []
    assert [d.code for d in validate_source(text, schema, renders=[ok, broken])] == [CODE_TEMPLATE]


def only_of(diagnostics):
    assert len(diagnostics) == 1, "expected exactly one finding, got %r" % (diagnostics,)
    return diagnostics[0]


# ---- what is marked manufacturable -----------------------------------------


def made(text, variables=None):
    return rendered(text, variables, manufacturable=True)


def test_a_manufacturable_assembly_connects_what_it_places():
    text = """
location: [[0, 0, 0], [0, 0, 1], 0]
links:
  - part: frame
  - part: bracket
    connect:
      name: frame
  - part: motor
    location: [[0, 0, 5], [0, 0, 1], 0]
  - part: loose
"""
    diagnostics = made(text)
    assert [d.code for d in diagnostics] == [CODE_MANUFACTURABLE, CODE_MANUFACTURABLE]
    located, loose = diagnostics
    # At the key that has to go, and the root's own placement is not one.
    assert text.split("\n")[located.line][located.column :].startswith("location:")
    assert "'motor' is placed by coordinates" in located.message
    assert "'loose' says neither where it goes nor what holds it" in loose.message
    # Not marked, the same file is somebody's work in progress.
    assert rendered(text) == []


def test_even_the_first_item_is_not_placed_by_coordinates():
    diagnostic = only_of(made("links:\n  - part: frame\n    location: [[0, 0, 0], [0, 0, 1], 0]\n"))
    assert "'frame' is placed by coordinates" in diagnostic.message


def test_every_links_list_has_its_own_first_item():
    text = """
links:
  - part: frame
  - name: arm
    connect:
      name: frame
    links:
      - part: upper
      - part: lower
        location: [[0, 0, 5], [0, 0, 1], 0]
"""
    diagnostic = only_of(made(text))
    assert "'lower'" in diagnostic.message


def test_the_rule_follows_what_renders():
    text = "links:\n  - part: frame\n{% for n in range(2) %}\n  - part: leg\n    location: {{ at }}\n{% endfor %}\n"
    diagnostic = only_of(made(text, {"at": "[[0, 0, 0], [0, 0, 1], 0]"}))
    assert diagnostic.line == 4


def config_made(text, inherited=None):
    return rendered(text, schema=PARTCAD_SCHEMA, inherited_manufacturable=inherited)


@pytest.mark.parametrize(
    "part",
    [
        "    type: step\n    manufacturing:\n      method: additive\n",
        "    type: step\n    vendor: McMaster\n    sku: 91290A115\n",
        "    type: alias\n    source: :other\n",
        "    type: enrich\n    source: :other\n",
        "    type: step\n    manufacturable: false\n",
    ],
)
def test_a_manufacturable_part_that_can_be_had_is_clean(part):
    assert config_made("manufacturable: true\nparts:\n  bolt:\n" + part) == []


@pytest.mark.parametrize(
    "config, inherited",
    [
        ("manufacturable: true\nparts:\n  bolt:\n    type: step\n", None),
        ("manufacturable: true\nparts:\n  bolt:\n    type: step\n    vendor: McMaster\n", None),
        ("parts:\n  bolt:\n    type: step\n    manufacturable: true\n", None),
        ("parts:\n  bolt:\n    type: step\n", True),
        ("manufacturable: false\nparts:\n  bolt:\n    type: step\n    manufacturable: true\n", None),
    ],
)
def test_a_manufacturable_part_nobody_could_make_or_buy(config, inherited):
    diagnostic = only_of(config_made(config, inherited))
    assert diagnostic.code == CODE_MANUFACTURABLE
    assert diagnostic.severity == SEVERITY_ERROR
    assert "'bolt' is marked manufacturable" in diagnostic.message
    assert config.split("\n")[diagnostic.line][diagnostic.column :].startswith("bolt:")


@pytest.mark.parametrize(
    "config, inherited",
    [
        # Nothing marks it: PartCAD takes it as manufacturable, but nobody said so yet.
        ("parts:\n  bolt:\n    type: step\n", None),
        ("manufacturable: false\nparts:\n  bolt:\n    type: step\n", True),
        ("parts:\n  bolt:\n    type: step\n", False),
    ],
)
def test_a_part_nothing_marks_manufacturable_is_not_held_to_it(config, inherited):
    assert config_made(config, inherited) == []


def test_parts_a_configuration_declares_in_a_loop_are_each_checked():
    config = "manufacturable: true\nparts:\n{% for n in [3, 4] %}\n  m{{ n }}:\n    type: step\n{% endfor %}\n"
    diagnostics = config_made(config)
    assert sorted(d.message.split("'")[1] for d in diagnostics) == ["m3", "m4"]
    assert {d.line for d in diagnostics} == {3}


def test_a_file_that_is_one_placed_item_is_that_item():
    """Its root is not the frame of a list, so a 'location:' on it is the item's own."""
    diagnostic = only_of(made("part: frame\nlocation: [[0, 0, 0], [0, 0, 1], 0]\n"))
    assert "'frame' is placed by coordinates" in diagnostic.message
    assert made("location: [[0, 0, 0], [0, 0, 1], 0]\nlinks:\n  - part: frame\n") == []


def test_an_include_that_is_not_found_is_checked_masked():
    text = "links:\n{% include 'legs.assy' %}\n  - part: frame\n"
    assert rendered(text) == []


def test_a_name_whose_value_is_a_template_line_is_not_missing():
    # Masked, an expression alone on its line reads as nothing at all.
    text = "links:\n  - part: a\n    name: first\n  - part: b\n    connect:\n      name:\n        {{ target }}\n"
    assert check(text) == []


@pytest.mark.parametrize("renders", [(), (Render({}),)])
def test_yaml_the_parser_raises_on_otherwise_is_a_finding_and_not_a_crash(renders):
    # An impossible date is a 'ValueError' out of PyYAML, not a 'YAMLError'.
    diagnostic = only_of(validate_source("desc: 2001-13-45\n", get_schema(PARTCAD_SCHEMA), renders=list(renders)))
    assert diagnostic.code == CODE_YAML
