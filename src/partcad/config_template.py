#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The names a package configuration may use while it is being rendered.

'partcad.yaml' is a Jinja2 template rendered to YAML before it is parsed (see
'ProjectLocal'), and this is what it is rendered with: the package's own name,
the handful of constants a CAD file keeps reaching for, and - since 0.8.77 -
which PartCAD is doing the rendering.

That last one is what lets one package serve two PartCADs. A package that wants
a feature this release has and the last one did not can write both forms and
pick between them, rather than raising its 'partcad:' requirement and going dark
for everyone who has not updated:

    {% if partcad_version_at_least("0.8.77") %}
    ... declared the way this PartCAD can read ...
    {% else %}
    ... declared the way every PartCAD can ...
    {% endif %}

A PartCAD that predates these names defines none of them, and a template that
named one would fail to render at all - so a package that has to work on those
too asks first, which is what 'is defined' is for:

    {% if partcad_version_major is defined and partcad_version_at_least("0.8.77") %}

Jinja2's 'and' short-circuits, so the call is not made where the name is absent.
"""

import math


def version_components(version: str) -> tuple[int, int, int]:
    """A version string as the three numbers it is made of.

    Anything that is not a number reads as zero rather than raising: this runs
    while a package is being loaded, and a version PartCAD itself could not
    parse is not a reason to refuse to load one.
    """
    numbers = []
    for part in str(version).split(".")[:3]:
        digits = ""
        for character in part:
            if not character.isdigit():
                break
            digits += character
        numbers.append(int(digits) if digits else 0)
    while len(numbers) < 3:
        numbers.append(0)
    return tuple(numbers)


def version_at_least(version: str, required) -> bool:
    """Whether 'version' is 'required' or newer, compared component by component.

    'required' is a version string ("0.8.77"), or the components as separate
    arguments through the wrapper below. Comparing the three numbers rather than
    the strings is the whole point: "0.8.9" is older than "0.8.77", and every
    string comparison says the opposite.
    """
    return version_components(version) >= version_components(required)


def render_context(package_name: str, version: str) -> dict:
    """Everything a 'partcad.yaml' is rendered with.

    A function rather than a literal because two of the names are derived from
    the version and one of them is a callable over it, and because the same
    context has to be buildable in a test without a package on disk.
    """
    major, minor, build = version_components(version)

    def at_least(*required) -> bool:
        """True when the PartCAD doing the rendering is this version or newer.

        Takes the version as a string - 'partcad_version_at_least("0.8.77")' -
        or as the numbers themselves, which is what a template that has already
        split them wants: 'partcad_version_at_least(0, 8, 77)'.

        A Python callable rather than a Jinja2 macro, which is what this looks
        like it should be. A macro always renders to *text*, so a false one
        comes back as the string "False" - which is not empty, and so is true
        to '{% if %}'. A comparison that reads as its own opposite is not a
        thing to leave lying in a template.
        """
        if len(required) == 1 and not isinstance(required[0], (int, float)):
            wanted = str(required[0])
        else:
            wanted = ".".join(str(int(number)) for number in required)
        return version_at_least(version, wanted)

    return {
        "package_name": package_name,
        # Which PartCAD is reading this package.
        "partcad_version": version,
        "partcad_version_major": major,
        "partcad_version_minor": minor,
        "partcad_version_build": build,
        "partcad_version_at_least": at_least,
        # The constants a CAD file keeps reaching for.
        "M_PI": math.pi,
        "PI": math.pi,
        "SQRT_2": math.sqrt(2),
        "SQRT_3": math.sqrt(3),
        "SQRT_5": math.sqrt(5),
        "INCH": 25.4,
        "INCHES": 25.4,
        "FOOT": 304.8,
        "FEET": 304.8,
        "get_from_config": lambda: None,
    }
