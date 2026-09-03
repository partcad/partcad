#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""conda/mamba: where PartCAD finds it, and the copy the standalone bundle carries.

PartCAD imports no CAD kernel. It provisions a Python environment and runs every
CAD script in that, and conda is the only sandbox that provisions an *interpreter*
along with it. For the wheels, asking the user for one is fair -- they brought
their own Python and can bring their own conda, and ``pythonSandbox`` falls back
to ``venv`` when they have not. For the standalone bundle neither half holds: the
bundle exists so that a machine with no Python at all can run PartCAD, and it
then turned around and asked that machine for conda. That is how the PartCAD IDE,
launching the daemon out of a bundle, failed on a clean machine.

The ``venv`` fallback does not rescue it either. A virtual environment is built
*from* an interpreter -- ``RuntimePythonVenv._host_interpreter()`` looks for
``python3`` and falls back to ``sys.executable``, which in a frozen bundle is
``pc`` and not a Python -- so on exactly the machine this artifact is for there
is nothing to build one from.

So the bundle carries one, and this module is the single place that knows where.
``dev-tools/pyinstaller/build.sh`` stages the payload after the freeze (the same
way it stages OpenSCAD) and ``find_bundled_executable()`` finds it again at run
time.

**The host's conda wins, and the bundled copy is the fallback.** That is the
opposite of what ``partcad.healthcheck.openscad`` does with the bundled OpenSCAD,
deliberately: OpenSCAD is one self-contained program with no state, so preferring
the bundled copy costs a user nothing and makes the bundle behave the same
everywhere. conda is not a program, it is an *installation* -- a channel
configuration the user chose and a package cache they have already paid
gigabytes for. Preferring ours would strand that cache and re-download the whole
CAD stack beside it, on a machine that was working perfectly well. So a machine
that has conda keeps behaving exactly as it did, and the bundled copy is what
makes a machine that has none work at all.

What the bundle carries is **micromamba**: mamba in its single-file,
dependency-free build. mamba because that is what PartCAD's CI provisions
(``use-mamba: true`` in ``.github/actions/setup-all/action.yml``) and what PartCAD
has always preferred over conda anyway; the single-file build because a
bundle is unpacked to an unpredictable path, and a Miniforge installation is not
relocatable -- its entry points hardcode the prefix they were installed into --
while this is one static executable that runs from wherever it finds itself. It
also resolves from conda-forge with no configuration at all, which is the channel
policy the comments in that CI action insist on: mixing Anaconda's ``defaults``
into a conda-forge environment is what made the macOS jobs segfault.
"""

import os
import shutil
import sys

# Where the bundle keeps its conda, relative to the directory holding the frozen
# interpreter. `build.sh` copies it there after PyInstaller has run, so this path
# exists only in a bundle -- a wheel and a source checkout have no payload.
BUNDLED_SUBPATH = ("conda", "micromamba.exe") if os.name == "nt" else ("conda", "micromamba")

# Where the bundled conda is told to keep its own state -- its package cache
# above all -- relative to PartCAD's internal state directory, beside the
# `sandbox` directory holding the environments it creates.
#
# It has to be told. micromamba's own default is `~/.local/share/mamba` (or
# `~/micromamba` for older releases), which is a directory PartCAD would be
# creating in the user's home without ever having said so -- outside anything
# `pc system status` reports or `pc system reset` clears, and outside what
# `snap remove --purge` takes away, since the snap moves PartCAD's state with
# `PC_INTERNAL_STATE_DIR` precisely so that it does. The internal state directory
# is the one PartCAD already owns, already documents, and already redirects.
ROOT_PREFIX_SUBDIR = "conda"


def find_bundled_executable() -> "str | None":
    """Return the conda shipped inside the standalone bundle, or None.

    None whenever PartCAD is not running from a bundle, and also when it is
    running from one built without the payload (a `pyinstaller partcad.spec` run
    by hand -- `build.sh` is what stages it).
    """
    if not getattr(sys, "frozen", False):
        return None

    # PyInstaller points `sys._MEIPASS` at the directory it unpacked the bundle
    # into, which is where the payload lives.
    bundle_dir = getattr(sys, "_MEIPASS", None)
    if not bundle_dir:
        return None

    path = os.path.join(bundle_dir, *BUNDLED_SUBPATH)
    if os.path.isfile(path) and os.access(path, os.X_OK):
        return path
    return None


def find_executable() -> "str | None":
    """Return the conda executable to run, or None if there is none.

    The host's mamba first, the host's conda second, the bundled copy last -- see
    the note at the top of this module for why the bundle does not go first.
    mamba before conda is the older preference of the two: it solves the CAD
    stack in a fraction of the time.

    This is deliberately cheap -- two PATH lookups and a stat, no subprocess --
    because `user_config` asks it on startup to decide whether `pythonSandbox`
    defaults to conda at all. `CondaPythonRuntime.find_conda_executable()` is the one that
    goes on to interrogate an importable conda module when this finds nothing.
    """
    for name in ("mamba", "conda"):
        path = shutil.which(name)
        if path:
            return path

    return find_bundled_executable()


def is_bundled(conda_path: "str | None") -> bool:
    """Whether `conda_path` is the copy this bundle carries rather than a host one."""
    return bool(conda_path) and conda_path == find_bundled_executable()


def bundled_command_env(internal_state_dir: str, env: "dict | None" = None) -> dict:
    """The environment the *bundled* conda has to be run in.

    Only the bundled one: a host conda knows its own root prefix, and telling it
    otherwise would move a package cache the user has been filling for years.

    An existing `MAMBA_ROOT_PREFIX` is left alone -- someone who runs their own
    micromamba has a cache worth sharing, and this is how they say so.
    """
    env = dict(os.environ if env is None else env)
    if not env.get("MAMBA_ROOT_PREFIX"):
        env["MAMBA_ROOT_PREFIX"] = os.path.join(internal_state_dir, ROOT_PREFIX_SUBDIR)
    return env
