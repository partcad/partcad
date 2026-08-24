#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The PYTHON* variables this harness was started with.

Importing `partcad` sweeps every PYTHON* variable out of `os.environ` (see
`partcad.python_env`): what PartCAD spawns is a sandbox interpreter, and it must
not inherit the module search path, the hash seed or anything else the user
happened to export. behave imports step modules, some of which import partcad,
so the sweep lands in *this* process too -- long before a scenario shells out to
`pc`, and taking with it the variables the CI workflow set for exactly those
subprocesses:

* `PYTHONPATH`, which carries `dev-tools/coverage-subprocess/sitecustomize.py`
  and is the only reason the daemon side of a scenario is measured at all.
* `PYTHONUTF8`/`PYTHONIOENCODING`, exported so that every process in the run
  agrees on UTF-8 rather than on whatever the OS defaults to.

They are captured here and put back on the environment each scenario hands to a
subprocess. `features/environment.py` imports this module, and behave loads that
before any step definition, so the snapshot is always taken before a sweep can
happen.
"""

import os

PYTHON_ENV = {name: value for name, value in os.environ.items() if name.startswith("PYTHON")}
