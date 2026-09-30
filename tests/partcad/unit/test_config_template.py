#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The names a 'partcad.yaml' is rendered with, and the version among them.

A package that wants a feature this PartCAD has and the last one did not can
write both forms and pick between them, instead of raising its 'partcad:'
requirement and going dark for everyone who has not updated. That only works if
the comparison is right about versions like "0.8.9" and "0.8.77", and if a
package can ask the question at all on a PartCAD that answers none of it.
"""

import jinja2
import pytest

import partcad as pc
from partcad import config_template

PACKAGE = "tests/partcad/unit/data/config_template/partcad.yaml"


def _render(source, version="0.8.77"):
    return jinja2.Environment().from_string(source).render(config_template.render_context("//test", version))


# --- the comparison ----------------------------------------------------------


@pytest.mark.parametrize(
    "version, components",
    [
        ("0.8.76", (0, 8, 76)),
        ("1.2", (1, 2, 0)),
        ("2", (2, 0, 0)),
        ("1.0.0rc1", (1, 0, 0)),
        ("", (0, 0, 0)),
    ],
)
def test_a_version_reads_as_its_three_numbers(version, components):
    assert config_template.version_components(version) == components


@pytest.mark.parametrize(
    "version, required, expected",
    [
        ("0.8.77", "0.8.77", True),
        ("0.8.78", "0.8.77", True),
        ("0.9.0", "0.8.77", True),
        ("1.0.0", "0.8.77", True),
        ("0.8.76", "0.8.77", False),
        # The one a string comparison gets backwards, which is why the numbers
        # are compared one at a time.
        ("0.8.9", "0.8.77", False),
        ("0.8.77", "0.8.9", True),
    ],
)
def test_a_version_is_compared_number_by_number(version, required, expected):
    assert config_template.version_at_least(version, required) is expected


# --- what a template sees ----------------------------------------------------


def test_the_version_is_there_whole_and_in_pieces():
    rendered = _render(
        "{{ partcad_version }}|{{ partcad_version_major }}" ".{{ partcad_version_minor }}.{{ partcad_version_build }}",
        version="1.2.3",
    )
    assert rendered == "1.2.3|1.2.3"


def test_the_comparison_is_a_real_boolean():
    """Not a Jinja2 macro: a macro renders to text, and "False" is a true string."""
    assert _render("{{ partcad_version_at_least('0.8.77') }}", "0.8.77") == "True"
    assert _render("{% if partcad_version_at_least('0.9') %}yes{% else %}no{% endif %}", "0.8.77") == "no"
    assert _render("{% if partcad_version_at_least('0.8') %}yes{% else %}no{% endif %}", "0.8.77") == "yes"


def test_the_comparison_also_takes_the_numbers_themselves():
    assert _render("{{ partcad_version_at_least(0, 8, 77) }}", "0.8.77") == "True"
    assert _render("{{ partcad_version_at_least(0, 9) }}", "0.8.77") == "False"


def test_a_package_can_ask_before_it_names_any_of_this():
    """A PartCAD that predates these names defines none of them.

    Naming one there fails the render outright, so a package that has to work on
    those asks first - and Jinja2's 'and' short-circuits, so the call is never
    made where the name is absent.
    """
    guarded = (
        "{% if partcad_version_major is defined and partcad_version_at_least('0.8.77') %}new{% else %}old{% endif %}"
    )
    assert jinja2.Environment().from_string(guarded).render({}) == "old"
    assert _render(guarded, "0.8.77") == "new"


def test_the_constants_a_cad_file_reaches_for_are_still_there():
    assert _render("{{ INCH }}|{{ FOOT }}|{{ package_name }}") == "25.4|304.8|//test"
    assert _render("{{ '%.4f' % PI }}") == "3.1416"


# --- and in a package on disk ------------------------------------------------


def test_a_package_takes_the_branch_its_partcad_can_read(monkeypatch):
    monkeypatch.setattr(pc, "__version__", "0.8.76")
    project = pc.Context(PACKAGE).get_project("//")
    assert project.get_interface("chosen").desc == "what an older PartCAD reads"
    assert sorted(project.interface_configs) == ["chosen"]

    monkeypatch.setattr(pc, "__version__", "0.8.77")
    project = pc.Context(PACKAGE).get_project("//")
    assert project.get_interface("chosen").desc == "what a newer PartCAD reads"
    assert sorted(project.interface_configs) == ["chosen", "only-for-the-new"]
