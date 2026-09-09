#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""``dockerImage``: where a package says which image its sandbox is built from.

The key is a *preference*, not a requirement, and most of what is worth pinning
is that distinction. A machine using another sandbox ignores it and installs
``pythonRequirements`` like any other package, which is why a package declaring
one still has to declare those.
"""

import types

from partcad import output, runtime_python


def _impl(section, format_name, config, project=None):
    made = output.Implementation(section, format_name, config)
    made.project = project
    return made


def _project(config_obj=None, declared=None):
    return types.SimpleNamespace(
        config_obj=config_obj or {},
        docker_image_declared=declared,
        python_version_declared=None,
    )


# --------------------------------------------------------------------------- #
# Where it is read from                                                        #
# --------------------------------------------------------------------------- #


def test_a_file_type_names_its_own_image():
    project = _project({"cae": {"fea": {"dockerImage": "ghcr.io/x/solver:abc"}}})
    assert _impl(output.CAE, "fea", {}, project).docker_image == "ghcr.io/x/solver:abc"


def test_a_package_may_say_it_once_for_every_file_type_it_implements():
    project = _project({"cae": {"fea": {}}}, declared="ghcr.io/x/solver:abc")
    assert _impl(output.CAE, "fea", {}, project).docker_image == "ghcr.io/x/solver:abc"


def test_the_file_type_wins_over_the_package():
    """One file type needing something the others do not is why both levels exist."""
    project = _project(
        {"cae": {"fea": {"dockerImage": "ghcr.io/x/fea:abc"}}},
        declared="ghcr.io/x/solver:abc",
    )
    assert _impl(output.CAE, "fea", {}, project).docker_image == "ghcr.io/x/fea:abc"


def test_a_package_that_names_none_gets_none():
    assert _impl(output.CAE, "fea", {}, _project({"cae": {"fea": {}}})).docker_image is None


def test_it_is_read_from_the_implementing_package_and_not_the_caller():
    """The caller may be a package of STEP files that has never heard of Python.

    'config' here is the layered configuration a caller contributes to; the
    declaration is read from the project that ships the script, so a copy of the
    key reaching the merged options is inert -- exactly as it is for
    'pythonVersion' and 'pythonRequirements'.
    """
    made = _impl(output.CAE, "fea", {"dockerImage": "ghcr.io/caller/wrong:1"}, _project({"cae": {"fea": {}}}))
    assert made.docker_image is None


def test_nothing_is_read_before_the_implementing_package_is_known():
    """'project' is set when the script is materialised, and not before."""
    assert _impl(output.CAE, "fea", {"dockerImage": "ghcr.io/x/solver:abc"}).docker_image is None


# --------------------------------------------------------------------------- #
# What it is not                                                               #
# --------------------------------------------------------------------------- #


def test_it_is_one_of_the_keys_that_describe_an_implementation():
    """So it is hidden from the parameters handed to the script, like the rest."""
    assert "dockerImage" in output.IMPLEMENTATION_KEYS


def test_declaring_an_image_does_not_remove_the_requirements():
    """An image says where a package runs best, not where it runs at all."""
    project = _project(
        {"cae": {"fea": {"dockerImage": "ghcr.io/x/solver:abc", "pythonRequirements": ["numpy==2.4.1"]}}}
    )
    made = _impl(output.CAE, "fea", {}, project)
    assert made.docker_image == "ghcr.io/x/solver:abc"
    assert made.python_requirements == ["numpy==2.4.1"]


# --------------------------------------------------------------------------- #
# A shape's own image, and its package's                                       #
# --------------------------------------------------------------------------- #
#
# The file types above are how an *implementation* names an image. A part, a
# sketch or a plugin names one directly, in its own configuration, and the
# factories that build them read that -- which they did not, so a part naming an
# image was rendered without it, in an environment that could be missing exactly
# the native library the part named it for.


def test_a_shape_names_its_own_image():
    project = types.SimpleNamespace(docker_image_declared="ghcr.io/x/package:abc")
    assert runtime_python.shape_docker_image({"dockerImage": "ghcr.io/x/part:def"}, project) == "ghcr.io/x/part:def"


def test_a_shape_that_names_none_gets_its_package_s():
    project = types.SimpleNamespace(docker_image_declared="ghcr.io/x/package:abc")
    assert runtime_python.shape_docker_image({}, project) == "ghcr.io/x/package:abc"
    assert runtime_python.shape_docker_image(None, project) == "ghcr.io/x/package:abc"


def test_no_image_anywhere_is_no_image():
    """Which is what makes PartCAD use its own."""
    assert runtime_python.shape_docker_image({}, types.SimpleNamespace()) is None
