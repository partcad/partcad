#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for ``partcad_utils.template_render``: rendering a template, and the way back to it.

What is pinned is the promise the linter builds on: any position in the
rendered text names the source line and column it came from -- the very
character for literal text, the ``{{ }}`` for what an expression produced, the
call for what a macro produced -- and a template that raises says on which line.
"""

import pytest

from partcad_utils import template_render


def where(source, rendering, needle, occurrence=0):
    """The source text at the position the ``occurrence``-th rendered ``needle`` maps to."""
    lines = rendering.text.split("\n")
    seen = 0
    for line_number, line in enumerate(lines):
        column = line.find(needle)
        while column != -1:
            if seen == occurrence:
                source_line, source_column = rendering.position(line_number, column)
                return source.split("\n")[source_line][source_column:]
            seen += 1
            column = line.find(needle, column + 1)
    raise AssertionError("%r not rendered %d times" % (needle, occurrence + 1))


def test_literal_text_maps_to_itself():
    source = "a: 1\nb:\n  - c\n"
    rendering = template_render.render(source, {})
    # Jinja2 drops one trailing newline, for PartCAD as much as here.
    assert rendering.text == source[:-1]
    assert where(source, rendering, "c") == "c"
    assert rendering.position(1, 0) == (1, 0)


def test_each_pass_of_a_loop_maps_to_the_body():
    source = "items:\n{% for x in [1, 2, 3] %}\n  - leg-{{ x }}\n{% endfor %}\n"
    rendering = template_render.render(source, {})
    assert rendering.text.count("leg-") == 3
    for occurrence in range(3):
        assert where(source, rendering, "leg-", occurrence) == "leg-{{ x }}"


def test_what_an_expression_produced_maps_to_the_expression():
    source = "location: [[{{ x * 2 }}, 0, 0], [0, 0, 1], 0]\n"
    rendering = template_render.render(source, {"x": 21})
    assert "42" in rendering.text
    assert where(source, rendering, "42") == "{{ x * 2 }}, 0, 0], [0, 0, 1], 0]"
    # And the literal text after it is back in step with the source.
    assert where(source, rendering, "[0, 0, 1]") == "[0, 0, 1], 0]"


def test_text_after_a_tag_on_the_same_line_is_found_outside_the_tag():
    # The `x` of the loop variable is not the `x` written after the tag.
    source = "{% for x in [1] %}x: {{ x }}{% endfor %}\n"
    rendering = template_render.render(source, {})
    line, column = rendering.position(0, 0)
    assert (line, column) == (0, source.index("%}x") + 2)


def test_a_macro_maps_to_where_it_is_called():
    source = "{% macro leg(n) %}\n  - part: leg{{ n }}\n{% endmacro %}\nlinks:\n{{ leg(1) }}\n"
    rendering = template_render.render(source, {})
    assert where(source, rendering, "part: leg1") == "{{ leg(1) }}"


def test_a_block_set_maps_to_where_it_is_printed():
    source = "{% set fragment %}\n  - part: a\n{% endset %}\nlinks:\n{{ fragment }}\n"
    rendering = template_render.render(source, {})
    assert where(source, rendering, "part: a") == "{{ fragment }}"


def test_an_include_maps_to_the_include(tmp_path):
    (tmp_path / "legs.yaml").write_text("  - part: leg\n")
    source = "links:\n{% include 'legs.yaml' %}\n"
    rendering = template_render.render(source, {}, [tmp_path])
    assert where(source, rendering, "part: leg") == "{% include 'legs.yaml' %}"


def test_comments_and_whitespace_control_keep_columns():
    source = "a: 1 {# note #} b\n{%- if true %}\nc: 2\n{%- endif %}\n"
    rendering = template_render.render(source, {})
    assert where(source, rendering, "b") == "b"
    assert where(source, rendering, "c: 2") == "c: 2"


def test_windows_line_endings():
    source = "a: 1\r\n{% for x in [1, 2] %}\r\nb{{ x }}: 2\r\n{% endfor %}\r\n"
    rendering = template_render.render(source, {})
    assert where(source, rendering, "b2") == "b{{ x }}: 2\r"


def test_a_span_ends_where_its_last_character_came_from():
    source = "name: {{ n }}_head\n"
    rendering = template_render.render(source, {"n": "arm"})
    line = rendering.text.split("\n")[0]
    start, end = rendering.span((0, line.index("arm")), (0, len(line)))
    assert start == (0, source.index("{{"))
    assert end == (0, len(source.rstrip("\n")))


@pytest.mark.parametrize(
    "source, line, message",
    [
        ("a: 1\nb: {{ missing_function() }}\n", 1, "'missing_function' is undefined"),
        ("a: 1\n\nb: {{ x * 2 }}\n", 2, "'x' is undefined"),
        ("{% for i in [1] %}\n  c: {{ 1 / 0 }}\n{% endfor %}\n", 1, "ZeroDivisionError"),
    ],
)
def test_a_template_that_raises_says_where(source, line, message):
    with pytest.raises(template_render.RenderError) as raised:
        template_render.render(source, {})
    assert raised.value.line == line
    assert message in raised.value.message


def test_a_template_that_does_not_parse_says_where():
    with pytest.raises(template_render.RenderError) as raised:
        template_render.render("a: 1\n{% for %}\n", {})
    assert raised.value.line == 1


def test_the_sandbox_is_kept():
    with pytest.raises(template_render.RenderError):
        template_render.render("{{ ''.__class__.__mro__ }}", {})


def test_a_tag_after_another_on_the_same_line_is_found_by_its_name(tmp_path):
    (tmp_path / "frag.yaml").write_text("  - part: included\n")
    source = "links:\n{% if true %}{% include 'frag.yaml' %}{% endif %}\n"
    rendering = template_render.render(source, {}, [tmp_path])
    assert where(source, rendering, "included") == "{% include 'frag.yaml' %}{% endif %}"


def test_an_expression_that_starts_on_the_line_before_its_value():
    # Jinja2 numbers the expression by its first token, on the next line.
    source = "links:\n  - part: a\n    location: {{\n 'oops' }}\n"
    rendering = template_render.render(source, {})
    assert where(source, rendering, "oops") == "{{"


@pytest.mark.parametrize(
    "source",
    [
        "desc: {{ 'a' * 10**8 }}\n",
        "desc: {{ [1] * 10**8 }}\n",
        "desc: {{ 2 ** 100000000 }}\n",
        "{% for i in range(100000) %}{% for j in range(100000) %}x{% endfor %}{% endfor %}",
    ],
)
def test_a_template_that_would_take_forever_is_stopped(source):
    with pytest.raises(template_render.RenderError):
        template_render.render(source, {})


def test_what_a_template_reads_is_listed_for_a_cache(tmp_path):
    (tmp_path / "a.yaml").write_text("{% include 'b.yaml' %}")
    (tmp_path / "b.yaml").write_text("b: 1\n")
    found, missing, dynamic = template_render.referenced_files(
        "{% include 'a.yaml' %}{% import 'nowhere.j2' as n %}", [tmp_path]
    )
    assert found == sorted([str(tmp_path / "a.yaml"), str(tmp_path / "b.yaml")])
    assert missing == ["nowhere.j2"]
    assert dynamic is False
    assert template_render.referenced_files("{% include which %}", [tmp_path])[2] is True
