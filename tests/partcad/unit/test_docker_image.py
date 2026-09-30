#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The name PartCAD pulls, given the one a package declared.

One line in a `partcad.yaml` has to work on every machine the image was built
for, and adding an architecture later has to be a new tag rather than an edit to
every package that names it. That is what the suffix is for, and these are the
cases where appending one naively would produce something that is not the image
anybody meant.
"""

from partcad import docker_image


def test_the_architecture_is_appended_to_the_tag():
    assert docker_image.candidates("ghcr.io/x/solver:abc123", machine="aarch64") == [
        "ghcr.io/x/solver:abc123-arm64",
        "ghcr.io/x/solver:abc123",
    ]


def test_the_declared_name_is_always_a_candidate():
    """Nothing here may make a reference unpullable that would have worked."""
    for machine in ("x86_64", "aarch64", "riscv64", "sparc"):
        assert "ghcr.io/x/solver:abc123" in docker_image.candidates("ghcr.io/x/solver:abc123", machine=machine)


def test_an_untagged_name_is_latest():
    """'ghcr.io/x/solver' means ':latest', so ':latest' is what gets suffixed."""
    assert docker_image.candidates("ghcr.io/x/solver", machine="x86_64") == [
        "ghcr.io/x/solver:latest-amd64",
        "ghcr.io/x/solver",
    ]


def test_a_registry_port_is_not_a_tag():
    """The colon in 'localhost:5000/x/solver' belongs to the host.

    Split on the last colon without looking at the last slash and the suffix
    lands inside the port number, producing a name that resolves to nothing.
    """
    assert docker_image.candidates("localhost:5000/x/solver", machine="x86_64") == [
        "localhost:5000/x/solver:latest-amd64",
        "localhost:5000/x/solver",
    ]
    assert docker_image.candidates("localhost:5000/x/solver:v2", machine="x86_64") == [
        "localhost:5000/x/solver:v2-amd64",
        "localhost:5000/x/solver:v2",
    ]


def test_a_digest_names_one_image_already():
    """No tag to suffix, and nothing to fall back to."""
    ref = "ghcr.io/x/solver@sha256:" + "0" * 64
    assert docker_image.candidates(ref, machine="aarch64") == [ref]


def test_an_architecture_with_no_conventional_name_falls_straight_through():
    """A suffix nobody publishes under is worse than no suffix at all."""
    assert docker_image.arch_suffix("riscv64") is None
    assert docker_image.candidates("ghcr.io/x/solver:abc123", machine="riscv64") == ["ghcr.io/x/solver:abc123"]


def test_docker_spellings_win_over_the_platform_module():
    """These name images, and Docker is what pulls them.

    'platform.machine()' says 'x86_64' where Docker says 'amd64', and an image
    built with '--platform linux/amd64' is tagged the way Docker says it.
    """
    assert docker_image.arch_suffix("x86_64") == "amd64"
    assert docker_image.arch_suffix("aarch64") == "arm64"
    assert docker_image.arch_suffix("AMD64") == "amd64"
