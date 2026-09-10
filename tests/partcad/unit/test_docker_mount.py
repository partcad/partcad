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


def test_everything_is_mounted_writable():
    """The installation was briefly mounted 'ro' and is not any more.

    It bought little -- a wrapper is read and executed, and what it writes goes
    to the cache or back over its own protocol -- and cost a second thing that
    could differ between two containers of one image. The isolation worth
    having is the container.
    """
    assert docker_mount.mounts(["/opt/partcad", "/srv/pkg"], windows=False) == {
        "/opt/partcad": {"bind": "/opt/partcad", "mode": "rw"},
        "/srv/pkg": {"bind": "/srv/pkg", "mode": "rw"},
    }


def test_a_nested_directory_is_seen_whichever_separator_it_is_written_with():
    """Otherwise neither is seen to contain the other and both are mounted.

    Which is the two views of one directory this function exists to prevent.
    """
    assert docker_mount.contains("C:/work", "C:\\work\\pkg", windows=True) is True
    assert docker_mount.mounts(["C:/work", "C:\\work\\pkg"], windows=True) == {
        "C:/work": {"bind": "/c/work", "mode": "rw"},
    }


def test_a_nested_directory_is_seen_whatever_its_case_on_windows():
    """'C:\\Users\\you' and 'c:/users/you/.partcad' are a parent and a child."""
    assert docker_mount.contains("C:\\Users\\you", "c:/users/you/.partcad", windows=True) is True


def test_case_still_decides_off_windows():
    """Two directories differing in case are two directories on a POSIX host."""
    assert docker_mount.contains("/srv/partcad", "/srv/PartCAD", windows=False) is False
    assert len(docker_mount.mounts(["/srv/PartCAD", "/srv/partcad"], windows=False)) == 2


def test_a_backslash_is_a_file_name_character_off_windows():
    """So folding it there would merge two directories that are two."""
    assert docker_mount.contains("/srv/work", "/srv/work\\pkg", windows=False) is True
    assert docker_mount.contains("/srv/work", "/srv/work-other", windows=False) is False


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


def test_an_argument_is_matched_whichever_separator_it_is_written_with():
    """An argument built with one and a mount recorded with the other.

    Left alone, it reached the container as a host path -- a file the
    interpreter over there has no such name for.
    """
    assert docker_mount.rewrite("C:/work/pkg/part.py", [r"C:\work"], windows=True) == "/c/work/pkg/part.py"
    assert docker_mount.rewrite(r"C:\work\pkg\part.py", ["C:/work"], windows=True) == "/c/work/pkg/part.py"
