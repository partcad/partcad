#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The Python environment PartCAD hands down to the processes it spawns.

Everything PartCAD executes in a Python sandbox -- the wrappers, "pip install",
"-m venv", conda itself -- is a child of this process and inherits this
process's environment. Whatever ``PYTHON*`` variables the user happened to have
exported therefore reach the sandbox, and two of the things they can decide
there are correctness and reproducibility:

* ``PYTHONPATH``/``PYTHONHOME`` point an otherwise pristine sandbox interpreter
  at somebody else's packages, which is how a sandbox pinned to one OCP build
  ends up importing another one.
* ``PYTHONHASHSEED`` is unset by default, so every child gets a *random* hash
  seed and any output whose order comes from set/dict iteration over strings
  differs from run to run.

The sandbox used to defend against the first of those by running every
interpreter with ``-I``, which (among other things) implies ``-E``: ignore all
``PYTHON*`` variables. That closed the hole, but it also made the second one
unfixable, because ``PYTHONHASHSEED`` is a ``PYTHON*`` variable and ``-E``
ignores it too -- there is no command line flag to pin the hash seed.

So the isolation is done here instead, once, on the environment itself: drop
every ``PYTHON*`` variable as PartCAD starts and put back exactly the ones
PartCAD wants. Children then inherit an environment that is already clean, the
interpreters no longer need ``-I`` (only ``-s``, which ``-I`` also implied and
which no environment variable can express as reliably), and the variables
PartCAD does set are finally honored.

Note this deliberately mutates the *current* process's environment rather than
building a private copy for each spawn: PartCAD spawns Python from several
places (the runtimes, conda, the daemon), and a copy made in one of them is a
copy the others do not have.
"""

import os

# Applied to the environment after the PYTHON* sweep below. These are inherited
# by every process PartCAD spawns; they are not read by the current process,
# which has long finished starting up by the time this runs.
PARTCAD_PYTHON_ENV = {
    # Pin the hash seed so that set/dict iteration over strings is the same on
    # every run. Rendered output that derives an order from such an iteration
    # (DXF's CLASSES section, for one) is then byte-stable across runs, which is
    # what lets the checked-in examples act as a baseline.
    "PYTHONHASHSEED": "0",
    # The other half of what "-I" used to give us: keep the script's directory
    # (and, for "-m", the current directory) off sys.path, so a stray file in
    # the directory PartCAD runs from cannot shadow a module the sandbox
    # imports. This is "-P", spelled as a variable so that one setting covers
    # every process rather than every command line.
    #
    # It only arrived in 3.11, and an older interpreter ignores it in silence
    # rather than refusing it. So this does not protect a 3.10 sandbox, and
    # nothing here can: see PythonRuntime.__init__, which falls back to "-I" on
    # the commands that need it below sandbox_versions.MIN_PYTHON_VERSION_SAFE_PATH.
    # Those commands -- "-m venv" and "-m pip" -- are the only ones whose
    # sys.path[0] is a directory a user can write to, and they are also the only
    # ones with nothing to gain from the pinned seed "-I" costs them.
    "PYTHONSAFEPATH": "1",
}


def sanitize(env: dict = None) -> dict:
    """Drop every ``PYTHON*`` variable from `env`, then apply PARTCAD_PYTHON_ENV.

    Defaults to the current process environment. Returns the environment it
    acted on, so a caller with a private copy can chain the call.
    """
    if env is None:
        env = os.environ

    # On Windows os.environ upper-cases its keys and the OS matches them
    # case-insensitively, so an exact-case prefix test is right on both
    # platforms: on POSIX only "PYTHON*" is what the interpreter reads.
    for name in [name for name in env if name.startswith("PYTHON")]:
        del env[name]

    env.update(PARTCAD_PYTHON_ENV)
    return env
