#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Measure coverage in processes the test harness does not launch itself.

The behave suite drives `pc`, but a thin CLI command hands the work to the
per-workspace daemon -- a separate process, spawned by the CLI rather than by
the harness, where most of the code under test actually runs. `coverage run`
only traces the process it starts, so without this the daemon side would never
be measured.

This is coverage.py's documented mechanism for that case: with
COVERAGE_PROCESS_START naming a config file, `coverage.process_startup()`
starts tracing as the interpreter comes up. Putting it in a sitecustomize on
PYTHONPATH keeps it entirely inside the harness -- no product code knows or
cares whether it is being measured.

Enabled only where the harness sets COVERAGE_PROCESS_START (one CI cell); a
no-op everywhere else, including every developer's machine.
"""

import os

if os.environ.get("COVERAGE_PROCESS_START"):
    try:
        import coverage

        coverage.process_startup()
    except Exception:  # pragma: no cover - never break the program being measured
        pass
