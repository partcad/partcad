#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What `partcad_utils.lint_context` renders a file with, beyond what `partcad_client`'s tests cover.

The rules for naming an object in a parameter override: where the package is
known (the daemon), exactly as PartCAD matches it; where it is not (a client
checking one file), by the object's name, with or without a package.
"""

import pytest

from partcad_utils import lint_context

OVERRIDES = {
    "//pub/furniture:desk": {"length": "60"},
    ":chair": {"height": "40"},
    "table": {"width": "30"},
}


@pytest.mark.parametrize(
    "name, package, expected",
    [
        ("desk", "//pub/furniture", {"length": "60"}),
        ("desk", "//pub/other", {}),
        ("desk", "", {"length": "60"}),
        ("chair", "", {"height": "40"}),
        ("table", "", {"width": "30"}),
        # Exactly, where the package is known: PartCAD would not apply these.
        ("chair", "//pub/furniture", {}),
        ("table", "//pub/furniture", {}),
    ],
)
def test_an_override_names_its_object(name, package, expected):
    assert lint_context._overrides_for(name, package, OVERRIDES) == expected


def test_a_value_that_will_not_read_as_its_type_leaves_the_default():
    """As PartCAD leaves it: see 'partcad.config.apply_user_parameter_overrides'."""
    params = lint_context._template_params(
        "desk", {"parameters": {"length": {"type": "int", "default": 1}}}, {"length": "long"}
    )
    assert params["param_length"] == 1
