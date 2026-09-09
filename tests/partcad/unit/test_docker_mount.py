#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Where the host's directories appear inside the ``docker`` sandbox.

The answer is "where they already are", which is only interesting in the cases
where it cannot be: Windows, whose drive letters are not paths a Linux container
can have, and nested mounts, where two views of one directory would leave it
undecided which of them a write lands in.

Every test states ``windows`` rather than trusting the platform. The mapping is
used on exactly the platform where CI is slowest to tell you it is wrong.
"""

import pytest

from partcad import docker_mount

# --------------------------------------------------------------------------- #
# Identical paths                                                              #
# --------------------------------------------------------------------------- #


def test_a_posix_path_is_itself():
    """The whole point: nothing is translated, so nothing can be translated wrong."""
    assert docker_mount.translate("/home/you/.partcad", windows=False) == "/home/you/.partcad"


def test_a_posix_mount_binds_a_directory_onto_itself():
    assert docker_mount.mounts(["/home/you/.partcad"], windows=False) == {
        "/home/you/.partcad": {"bind": "/home/you/.partcad", "mode": "rw"},
    }


# --------------------------------------------------------------------------- #
# Windows                                                                      #
# --------------------------------------------------------------------------- #


def test_a_drive_letter_becomes_a_top_level_directory():
    """The way Docker Desktop mounts one, and the one place PartCAD translates."""
    assert docker_mount.translate(r"C:\Users\you\.partcad", windows=True) == "/c/Users/you/.partcad"


def test_the_drive_letter_is_lowercased_and_slashes_are_flipped():
    assert docker_mount.translate(r"D:\Work\pkg", windows=True) == "/d/Work/pkg"
    assert docker_mount.translate("D:/Work/pkg", windows=True) == "/d/Work/pkg"


def test_a_drive_root_is_the_directory_itself():
    assert docker_mount.translate("C:\\", windows=True) == "/c"


def test_a_network_path_is_refused_rather_than_mangled():
    """A bind mount pointing at the wrong place renders the wrong file."""
    with pytest.raises(docker_mount.UnmountablePath, match="network path"):
        docker_mount.translate(r"\\server\share\pkg", windows=True)


def test_a_path_with_no_drive_letter_is_refused():
    with pytest.raises(docker_mount.UnmountablePath, match="drive letter"):
        docker_mount.translate(r"pkg\part.py", windows=True)


# --------------------------------------------------------------------------- #
# What gets mounted                                                            #
# --------------------------------------------------------------------------- #


def test_a_directory_inside_another_is_not_mounted_twice():
    """Two views of one directory leave it undecided which a write lands in."""
    assert docker_mount.mounts(["/home/you", "/home/you/pkg"], windows=False) == {
        "/home/you": {"bind": "/home/you", "mode": "rw"},
    }


def test_siblings_are_both_mounted():
    assert docker_mount.mounts(["/home/you/.partcad", "/srv/pkg"], windows=False) == {
        "/home/you/.partcad": {"bind": "/home/you/.partcad", "mode": "rw"},
        "/srv/pkg": {"bind": "/srv/pkg", "mode": "rw"},
    }


def test_the_same_directory_named_twice_is_one_mount():
    assert len(docker_mount.mounts(["/srv/pkg", "/srv/pkg/"], windows=False)) == 1


def test_a_prefix_that_is_not_a_parent_is_not_swallowed():
    """'/srv/pkg' does not contain '/srv/pkg-other', textual prefix or not."""
    assert len(docker_mount.mounts(["/srv/pkg", "/srv/pkg-other"], windows=False)) == 2


def test_a_read_only_directory_is_mounted_read_only():
    """PartCAD's own installation: the sandbox runs the wrappers out of it."""
    assert docker_mount.mounts(["/opt/partcad", "/srv/pkg"], windows=False, read_only=["/opt/partcad"]) == {
        "/opt/partcad": {"bind": "/opt/partcad", "mode": "ro"},
        "/srv/pkg": {"bind": "/srv/pkg", "mode": "rw"},
    }


def test_a_trailing_separator_does_not_hide_a_read_only_mount():
    assert docker_mount.mounts(["/opt/partcad"], windows=False, read_only=["/opt/partcad/"]) == {
        "/opt/partcad": {"bind": "/opt/partcad", "mode": "ro"},
    }


def test_a_read_only_directory_inside_a_writable_one_is_reached_through_it():
    """A checkout with its virtual environment inside the package it is working on.

    The installation is then under the context root, which is mounted writable
    by intent. Narrowing the outer mount to protect the inner one would take
    write access away from the package being worked on, which is worse than what
    it would prevent -- and dropping the outer one is not on the table either.
    """
    assert docker_mount.mounts(
        ["/srv/pkg", "/srv/pkg/.venv/lib/python3.11/site-packages/partcad"],
        windows=False,
        read_only=["/srv/pkg/.venv/lib/python3.11/site-packages/partcad"],
    ) == {"/srv/pkg": {"bind": "/srv/pkg", "mode": "rw"}}


# --------------------------------------------------------------------------- #
# Rewriting a command line                                                     #
# --------------------------------------------------------------------------- #


def test_nothing_is_rewritten_off_windows():
    argument = "/home/you/.partcad/sandbox/pc-py-docker-abc-3.11/bin/python"
    assert docker_mount.rewrite(argument, ["/home/you/.partcad"], windows=False) == argument


def test_an_argument_under_a_mount_is_rewritten():
    assert (
        docker_mount.rewrite(
            r"C:\Users\you\.partcad\sandbox\pc\bin\python.exe",
            [r"C:\Users\you\.partcad"],
            windows=True,
        )
        == "/c/Users/you/.partcad/sandbox/pc/bin/python.exe"
    )


def test_an_argument_under_no_mount_is_left_alone():
    """A flag, a module name, or a path to something that was never mounted."""
    assert docker_mount.rewrite("-m", [r"C:\Users\you\.partcad"], windows=True) == "-m"


def test_the_longest_mount_wins():
    """A nested mount must not half-rewrite a path belonging to the outer one."""
    assert (
        docker_mount.rewrite(
            r"C:\work\pkg\part.py",
            [r"C:\work", r"C:\work\pkg"],
            windows=True,
        )
        == "/c/work/pkg/part.py"
    )


def test_a_drive_letter_is_matched_whatever_its_case():
    """Windows says 'C:' and 'c:' for the same drive; both have to match."""
    assert docker_mount.rewrite(r"c:\work\pkg\part.py", [r"C:\work"], windows=True) == "/c/work/pkg/part.py"
