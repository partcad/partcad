#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""cadmpeg as a second opinion on what PartCAD read: 'cadmpeg measure' and 'cadmpeg diff'.

PartCAD reads a native CAD file through cadmpeg and OpenCASCADE, and measures
what it built with OpenCASCADE. cadmpeg measures the native file itself, from
its own decoded B-rep, by a method of its own (see its 'docs/measurement.md'):
every quantity comes with how it was obtained and how far it can be trusted. So
the two can be held against each other, and 'cadmpeg diff --geometry' does that
for two whole files, body by body.

Neither is a verdict on its own: cadmpeg says when it cannot measure a body
(its quadrature does not converge, a carrier has no measure), and that is data
rather than a failure. These helpers hand that through, and the tests decide
what to make of it.
"""

import importlib.util
import json
import os
import subprocess

from partcad import output

BUILTIN_IMPORT = output.BUILTIN_PATHS[output.BUILTIN_PACKAGES[output.IMPORT]]


def executable(ctx):
    """The cadmpeg PartCAD itself runs, fetched where the built-in readers keep it."""
    spec = importlib.util.spec_from_file_location(
        "cadmpeg_tool_for_tests", os.path.join(BUILTIN_IMPORT, "cadmpeg_tool.py")
    )
    tool = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(tool)
    return tool.executable(output.package_cache_dir(ctx, output.builtin_project(ctx, output.IMPORT)))


def _run(command):
    """Run cadmpeg, reading what it says as the UTF-8 it writes.

    Not as the locale's encoding, which is what 'text=True' alone decodes with:
    on Windows that is cp1252, which has no character for the bytes of the
    units cadmpeg writes (a superscript in 'mm^5'), and the decode failing
    leaves the output None rather than raising.
    """
    return subprocess.run(command, capture_output=True, encoding="utf-8", check=False)


def decode_as_windows_does(monkeypatch):
    """Have 'subprocess.run' decode text in cp1252 when the caller names no encoding.

    Which is what Windows does: 'text=True' alone decodes in the locale's
    encoding, and the runners' locale is cp1252. Wrapping the call rather than
    patching how subprocess picks the encoding, because that is private and
    differs between the Python versions PartCAD supports.
    """
    run = subprocess.run

    def run_as_on_windows(*args, **kwargs):
        if kwargs.get("encoding") is None and (kwargs.get("text") or kwargs.get("universal_newlines")):
            kwargs["encoding"] = "cp1252"
        return run(*args, **kwargs)

    monkeypatch.setattr(subprocess, "run", run_as_on_windows)


def measure(cadmpeg, path):
    """The body rows 'cadmpeg measure' reports for the file at 'path'."""
    result = _run([cadmpeg, "measure", str(path), "--json"])
    assert result.returncode == 0, result.stderr
    return json.loads(result.stdout)["measure"]["bodies"]


def diff(cadmpeg, a, b):
    """'cadmpeg diff --geometry' of two files: its exit status and its comparison.

    The status is 0 when the two agree and 1 when they differ or the comparison
    cannot decide; the comparison says which.
    """
    result = _run([cadmpeg, "diff", str(a), str(b), "--geometry", "--json"])
    report = json.loads(result.stdout)
    assert report["status"] == "ok", result.stderr
    return result.returncode, report["geometry"]["comparison"]


def volume(body):
    """A body row's volume, when cadmpeg measured one; None when it could not."""
    value = body.get("volume") or {}
    return value if value.get("status") == "measured" else None


def same_volume(a, b):
    """Whether two measured volumes agree within what cadmpeg says either may be off by."""
    allowed = sum(v.get("numeric_error", 0.0) + v.get("model_uncertainty", 0.0) for v in (a, b))
    return abs(a["value"] - b["value"]) <= allowed + 1e-6 * max(abs(a["value"]), abs(b["value"]))


def disagreements(comparison):
    """Every quantity 'cadmpeg diff' compared and found different, as '(body, quantity)'."""
    found = [
        (pair["a"], quantity["quantity"])
        for pair in comparison["pairs"]
        for quantity in pair["quantities"]
        if not quantity["agrees"]
    ]
    found += [("document", quantity["quantity"]) for quantity in comparison["document"] if not quantity["agrees"]]
    return found
