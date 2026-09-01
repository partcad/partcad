#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""How the Windows named-pipe daemon is started.

Windows has no `fork`, so the daemon is a *new process* rather than a copy of
this one -- which means the argv that starts it has to be right, and there is no
Windows runner in CI to notice when it is not. It was not: the frozen bundle is
a single executable that takes the service's own options, and it was being run
as `sys.executable -m partcad_service_json_rpc`, which it rejects. That bundle is
what the editor extension downloads and runs, so on Windows the daemon it asked
for was never there.

The spawn itself is Windows-only (detached process creation flags); what is
pinned here is the argv, which is neither.
"""

import sys

from partcad_service_json_rpc.win_pipe import _launcher_argv


def test_a_source_checkout_runs_the_module(monkeypatch):
    monkeypatch.delattr(sys, "frozen", raising=False)
    assert _launcher_argv() == [sys.executable, "-m", "partcad_service_json_rpc"]


def test_a_frozen_bundle_runs_itself(monkeypatch):
    # `partcad-json-rpc.exe --serve-pipe ...`, not `partcad-json-rpc.exe -m
    # partcad_service_json_rpc --serve-pipe ...`: the bundle's argument parser
    # has no `-m`, so the daemon exited before it served anything.
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert _launcher_argv() == [sys.executable]
