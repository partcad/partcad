#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PartCAD image's entrypoint, run here without Docker: as whom does it start `pc`?

`entrypoint.sh` is a POSIX shell script whose decisions are made with `id`,
`stat` and `setpriv`, so this runs the real script with those three -- and the
executables it hands over to -- replaced by stubs on `PATH`. `stat` answers from
a table rather than from the file system, because the uids that matter here are
ones no test machine has; `setpriv` and the PartCAD executables only write down
how they were called. The lists the image writes at build time -- `pc`'s
commands, and its options that take a value -- are written here by the
Dockerfile's own lines, run against this checkout's `pc`. What the image does in
a real container is `dev-tools/ci/test-partcad-image.sh`.
"""

import functools
import os
import pathlib
import re
import shutil
import socket
import subprocess
import sys

import pytest

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
IMAGE_DIR = REPO_ROOT / "tools" / "containers" / "partcad"
ENTRYPOINT = IMAGE_DIR / "entrypoint.sh"
SHARE_IN_IMAGE = "/usr/local/share/partcad/"

pytestmark = pytest.mark.skipif(
    sys.platform == "win32" or shutil.which("sh") is None, reason="the entrypoint is a POSIX shell script"
)

# A stub `stat -c %u|%g <path>`: the owner the table gives the path, after
# resolving it the way the entrypoint does, and root for anything not in it.
STAT = """#!/bin/sh
format="$2"
target="$(cd -P -- "$3" 2>/dev/null && pwd -P || printf '%s' "$3")"
while read -r path uid gid; do
  if [ "${path}" = "${target}" ]; then
    case "${format}" in %u) echo "${uid}" ;; %g) echo "${gid}" ;; esac
    exit 0
  fi
done < "${STUB_OWNERS}"
echo 0
"""

# `setpriv --reuid=U --regid=G --groups=L -- <command...>`: the socket check
# (`test ...`) succeeds or fails as asked; anything else is written down.
SETPRIV = """#!/bin/sh
uid="${1#--reuid=}"
gid="${2#--regid=}"
groups="${3#--groups=}"
shift 4
if [ "$1" = test ]; then
  [ -z "${STUB_SOCKET_DENIED:-}" ]
  exit
fi
printf 'setpriv %s %s %s %s\\n' "${uid}" "${gid}" "${groups}" "$*" >> "${STUB_LOG}"
"""

AS_IS = """#!/bin/sh
printf 'as-is %s\\n' "$(basename "$0") $*" >> "${STUB_LOG}"
"""


@functools.lru_cache(maxsize=None)
def _written_at_build_time():
    """``{name: content}`` of what the Dockerfile's `python3 -c "..." > /usr/local/share/partcad/<name>` write."""
    dockerfile = (IMAGE_DIR / "Dockerfile").read_text(encoding="utf-8")
    written = {}
    for code, name in re.findall(r'python3 -c "(.*?)" > %s(\w+)' % re.escape(SHARE_IN_IMAGE), dockerfile, re.S):
        # Inside the shell's double quotes a backslash-newline is a continuation, and nothing else is special here.
        done = subprocess.run(
            [sys.executable, "-c", code.replace("\\\n", "")], capture_output=True, text=True, check=True, timeout=300
        )
        written[name] = done.stdout
    return written


def test_the_lists_the_entrypoint_reads_are_the_ones_the_image_writes():
    written = _written_at_build_time()
    assert set(written) == {"commands", "options"}
    assert {"mcp", "render", "init"} <= set(written["commands"].split())
    options = set(written["options"].split())
    assert {"-p", "--path", "--threads-max", "--cache-s3-bucket"} <= options
    assert not {"-v", "--verbose", "--no-ansi", "--offline"} & options, "flags take no value"
    script = ENTRYPOINT.read_text(encoding="utf-8")
    for name in written:
        assert script.count(SHARE_IN_IMAGE + name) == 1, name


@pytest.fixture
def image(tmp_path):
    """A directory tree standing in for the container: stubs, the commands list, and a table of owners."""
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    stubs = {"id": '#!/bin/sh\necho "${STUB_ID}"\n', "stat": STAT, "setpriv": SETPRIV}
    for name in ("pc", "partcad", "partcad-json-rpc", "sh-tool"):
        stubs[name] = AS_IS
    for name, body in stubs.items():
        (bin_dir / name).write_text(body, encoding="utf-8")
        (bin_dir / name).chmod(0o755)

    share = tmp_path / "share"
    share.mkdir()
    for name, content in _written_at_build_time().items():
        (share / name).write_text(content, encoding="utf-8")
    script = ENTRYPOINT.read_text(encoding="utf-8").replace(SHARE_IN_IMAGE, "%s/" % share)
    entrypoint = tmp_path / "entrypoint.sh"
    entrypoint.write_text(script, encoding="utf-8")

    for name in ("work", "workspace", "workspace/sub", "workspace/sub/pkg", "elsewhere", "rootdir"):
        (tmp_path / name).mkdir(parents=True, exist_ok=True)
    (tmp_path / "workspace" / "partcad.yaml").write_text("", encoding="utf-8")
    owners = tmp_path / "owners"

    class Image:
        root = tmp_path

        def own(self, table):
            """``{relative path: (uid, gid)}``; anything else is root's."""
            owners.write_text(
                "".join("%s %s %s\n" % ((tmp_path / path).resolve(), uid, gid) for path, (uid, gid) in table.items()),
                encoding="utf-8",
            )

        def run(self, *args, cwd="work", uid=0, env=None):
            """Run the entrypoint; return (what was executed, standard output, standard error)."""
            log = tmp_path / "log"
            log.write_text("", encoding="utf-8")
            if not owners.exists():
                self.own({})
            environment = {
                "PATH": "%s:%s" % (bin_dir, os.environ.get("PATH", "/usr/bin:/bin")),
                "STUB_ID": str(uid),
                "STUB_OWNERS": str(owners),
                "STUB_LOG": str(log),
                "DOCKER_HOST": "unix://%s" % (tmp_path / "no-socket"),
            }
            environment.update(env or {})
            done = subprocess.run(
                ["sh", str(entrypoint), *args],
                cwd=tmp_path / cwd,
                env=environment,
                capture_output=True,
                text=True,
                timeout=60,
            )
            assert done.returncode == 0, done.stderr
            return log.read_text(encoding="utf-8").strip(), done.stdout, done.stderr

    return Image()


OWNERS = {"work": (999, 999), "workspace": (1000, 1000), "workspace/sub": (1000, 1000), "elsewhere": (1001, 1002)}


def test_the_docker_catalog_runs_pc_as_the_owner_of_the_mounted_workspace(image):
    """`-p /workspace mcp` from the image's own /work, as the catalog's `server.yaml` starts it: not /work's uid."""
    image.own(OWNERS)
    ran, _, _ = image.run("-p", str(image.root / "workspace"), "mcp")
    assert ran == "setpriv 1000 1000 1000 pc -p %s mcp" % (image.root / "workspace")


@pytest.mark.parametrize(
    "spelling",
    [
        lambda path: ["-p", path],
        lambda path: ["--path", path],
        lambda path: ["--path=" + path],
        lambda path: ["-p" + path],
        lambda path: ["--no-ansi", "-p", path, "-v"],
        lambda path: ["--threads-max", "4", "-p", path],
        lambda path: ["-vp", path],
        lambda path: ["-vqp" + path],
        lambda path: ["-v", "-p", path, "--threads-max=4"],
        # The value of an option that takes one, however much it looks like a command, is not the command.
        lambda path: ["--cache-s3-bucket", "render", "-p", path],
        lambda path: ["--python-sandbox", "--offline", "-p", path],
    ],
)
def test_every_way_pc_reads_its_package_option(image, spelling):
    image.own(OWNERS)
    args = spelling(str(image.root / "elsewhere"))
    ran, _, _ = image.run(*args, "render")
    assert ran.startswith("setpriv 1001 1002 1002 pc "), ran


def test_the_first_argument_that_is_no_option_is_the_command(image):
    """`pc <command> -p <dir>` is that command's `-p`, whatever comes before it, and whether `pc` knows it or not."""
    image.own(OWNERS)
    elsewhere = str(image.root / "elsewhere")
    for args in (
        ["--offline", "render", "-p", elsewhere],
        ["-v", "no-such-command", "-p", elsewhere],
        ["--", "-p", elsewhere],
    ):
        ran, _, _ = image.run(*args)
        assert ran.startswith("setpriv 999 999 999 pc "), (args, ran)


def test_minus_p_equals_is_what_click_makes_of_it(image):
    """click reads `-p=DIR` as "=DIR", which is no directory: the working directory answers, as without `-p`."""
    image.own(OWNERS)
    ran, _, _ = image.run("-p=" + str(image.root / "elsewhere"), "render")
    assert ran.startswith("setpriv 999 999 999 pc "), ran


def test_the_package_may_be_named_by_pc_path(image):
    image.own(OWNERS)
    ran, _, _ = image.run("mcp", env={"PC_PATH": str(image.root / "elsewhere")})
    assert ran == "setpriv 1001 1002 1002 pc mcp"


def test_a_yaml_file_is_owned_by_whoever_owns_its_directory(image):
    image.own(OWNERS)
    ran, _, _ = image.run("-p", str(image.root / "workspace" / "partcad.yaml"), "mcp")
    assert ran.startswith("setpriv 1000 1000 1000 pc "), ran


def test_a_command_s_own_minus_p_is_not_the_package(image):
    """`pc init -p ...` and `pc supply quote -p ...` mean something else by it."""
    image.own(OWNERS)
    ran, _, _ = image.run("init", "-p", str(image.root / "elsewhere"))
    assert ran.startswith("setpriv 999 999 999 pc init"), ran


def test_without_a_package_the_working_directory_answers(image):
    """`-v "$PWD:$PWD" -w "$PWD" ... render my_part`, the documented `docker run`."""
    image.own(OWNERS)
    ran, _, _ = image.run("render", "my_part", cwd="workspace")
    assert ran == "setpriv 1000 1000 1000 pc render my_part"


def test_a_package_inside_the_working_directory_leaves_the_working_directory_the_answer(image):
    """`-w <workspace> ... -p <package> mcp`, as `pc init --mcp-via docker` writes it: unchanged by the package."""
    image.own({**OWNERS, "workspace/sub/pkg": (1001, 1002)})
    ran, _, _ = image.run("-p", "sub/pkg", "mcp", cwd="workspace")
    assert ran.startswith("setpriv 1000 1000 1000 pc "), ran
    ran, _, _ = image.run("-p", str(image.root / "workspace" / "sub" / "pkg"), "mcp", cwd="workspace")
    assert ran.startswith("setpriv 1000 1000 1000 pc "), ran


def test_a_relative_package_outside_the_working_directory_is_that_package(image):
    image.own(OWNERS)
    ran, _, _ = image.run("-p", "../elsewhere", "mcp", cwd="workspace")
    assert ran.startswith("setpriv 1001 1002 1002 pc "), ran


def test_a_root_owned_directory_keeps_root(image):
    image.own(OWNERS)
    ran, _, _ = image.run("-p", str(image.root / "rootdir"), "mcp")
    assert ran == "as-is pc -p %s mcp" % (image.root / "rootdir")
    ran, _, _ = image.run("render", cwd="rootdir")
    assert ran == "as-is pc render"


def test_a_package_that_is_not_there_leaves_the_working_directory_the_answer(image):
    """`pc` refuses it; the entrypoint does not guess, and does not fail before `pc` can say so."""
    image.own(OWNERS)
    ran, _, _ = image.run("-p", str(image.root / "missing"), "mcp")
    assert ran.startswith("setpriv 999 999 999 pc "), ran


def test_pc_uid_and_pc_gid_override(image):
    image.own(OWNERS)
    ran, _, _ = image.run("-p", str(image.root / "workspace"), "mcp", env={"PC_UID": "4242", "PC_GID": "4343"})
    assert ran.startswith("setpriv 4242 4343 4343 pc "), ran


def test_started_with_user_it_changes_nothing(image):
    image.own(OWNERS)
    ran, _, _ = image.run("-p", str(image.root / "workspace"), "mcp", uid=1234)
    assert ran == "as-is pc -p %s mcp" % (image.root / "workspace")


def test_a_command_that_is_not_partcad_runs_as_it_is(image):
    image.own(OWNERS)
    ran, _, _ = image.run("sh-tool", "-p", str(image.root / "workspace"))
    assert ran == "as-is sh-tool -p %s" % (image.root / "workspace")


def test_partcad_json_rpc_drops_to_the_working_directory_s_owner(image):
    image.own(OWNERS)
    ran, _, _ = image.run("partcad-json-rpc", "-p", str(image.root / "elsewhere"))
    assert ran.startswith("setpriv 999 999 999 partcad-json-rpc"), ran


def test_the_socket_s_group_is_added_and_nothing_goes_to_standard_output(image):
    path = image.root / "s"
    if len(str(path)) > 100:
        pytest.skip("the temporary directory is too deep for a unix socket's path")
    server = socket.socket(socket.AF_UNIX)
    try:
        server.bind(str(path))
        image.own({**OWNERS, "s": (0, 2375)})
        ran, out, err = image.run("-p", str(image.root / "workspace"), "mcp", env={"DOCKER_HOST": "unix://%s" % path})
        assert ran.startswith("setpriv 1000 1000 1000,2375 pc "), ran
        assert out == "" and err == ""

        ran, out, err = image.run(
            "-p",
            str(image.root / "workspace"),
            "mcp",
            env={"DOCKER_HOST": "unix://%s" % path, "STUB_SOCKET_DENIED": "1"},
        )
        assert ran.startswith("setpriv 1000 1000 1000,2375 pc "), ran
        assert out == "" and "cannot use the Docker socket" in err
    finally:
        server.close()


def test_nothing_goes_to_standard_output(image):
    image.own(OWNERS)
    for args in (["-p", str(image.root / "workspace"), "mcp"], ["--help"], ["sh-tool"]):
        _, out, _ = image.run(*args)
        assert out == ""
