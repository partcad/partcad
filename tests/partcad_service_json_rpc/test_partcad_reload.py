#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""`partcad` has to survive being reloaded, because the daemon reloads it.

`Session.load_partcad` drops every `partcad*` module out of `sys.modules` and
imports the package again on each `activate`, so PartCAD's global state does not
leak from one package load into the next. The daemon is warm and shared and the
VS Code extension activates on every connection, so the second window onto a
workspace takes the reload path while the first does not.

That is a path nothing else exercises. `partcad/__init__.py` aliases the
`partcad_utils` modules into the `partcad` namespace with a loop that ended in
`globals()[name] = module` -- and this package has a submodule named `globals`,
which `from .globals import ...` binds as an attribute of the package further
down. A reload re-runs the body against the dictionary the first run left
behind, where `globals` is that submodule, so the builtin was shadowed and the
call raised `TypeError: 'module' object is not callable`.

What the user saw was the VS Code Explorer reporting that PartCAD was not
installed, on a machine where it was installed, running, and the right version.

Run in a subprocess: the reload replaces module objects other tests in this
process are holding.
"""

import subprocess
import sys

# Imported the way the daemon does (`importlib.import_module`), reloaded the way
# the daemon does, and then used -- an alias the loop is responsible for, so a
# reload that "succeeds" without rebuilding the namespace still fails here.
PROGRAM = """
import importlib
import sys

partcad = importlib.import_module("partcad")
first = partcad.__version__

for name in sorted(sys.modules):
    if name == "partcad" or name.startswith("partcad."):
        del sys.modules[name]

partcad = importlib.reload(importlib.import_module("partcad"))
assert partcad.__version__ == first, "the reloaded package reports another version"

# The aliases the loop installs, both ways they are reached.
assert partcad.logging is sys.modules["partcad.logging"]
assert partcad.user_config is not None
assert callable(partcad.healthcheck.tests.run_healthchecks)

print("RELOADED")
"""


def test_partcad_survives_the_reload_the_daemon_does():
    proc = subprocess.run(
        [sys.executable, "-c", PROGRAM],
        capture_output=True,
        text=True,
        timeout=300,
    )
    assert proc.returncode == 0, f"reloading `partcad` failed:\n{proc.stderr}"
    assert "RELOADED" in proc.stdout
