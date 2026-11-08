#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for a qualification plugin.

The counterpart of 'wrapper_simulate.py' for the 'qual:' section: a check of an
object that a package supplies -- a 'basic', 'topology' or 'other' one (see
'partcad.qual') -- is a Python script run through here, inside a PartCAD sandbox
with whatever its declaration says it needs.

The contract is narrow, like a simulation plugin's:

  **what is known about the object goes in, a verdict and what was found come out.**

The script is executed with these globals available:

    request  -- 'qualification' (the name the object declared the check under),
                'subtype', 'subject' (the object's full path), 'subject_kind'
                ('part', 'assembly', 'scene' or 'sketch'), 'package_dir' (the
                directory of the object's package, where a file the check reads
                beside it is), 'subject_file' and 'subject_format' when the
                plugin declares a 'format:' to be handed the object in, 'params'
                (every parameter, the plugin's defaults under what the object
                says), and every parameter again at the top level, as a
                simulation plugin is handed them
    path     -- a directory the run may write into: a report, the geometry a
                topology check points at

and reports in one of two ways, whichever suits it:

    output = {"success": True, "passed": True, ...}

or by defining 'process(path, request)', which returns the same. What it may say:

    passed      True or False; None (or absent) for "could not be answered here",
                which is reported as a skip with 'skipped' as the reason
    findings    a list of {'level': 'error' | 'warning' | 'info', 'text': ...},
                what was found, in words
    report      for an 'other' check, a table of the tool's own: see
                'partcad.qual.qualification.OtherQualification'
    highlights  for a 'topology' check, the geometry the findings are about: a
                list of {'name', 'kind': 'face' | 'edge' | 'volume', 'file'},
                each 'file' an OCCT BREP file the plugin wrote under 'path'

Nothing here imports OCP: a check of somebody else's has no reason to carry a
CAD kernel, and one that writes geometry brings its own.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import process_tree
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version').
CACHE_VERSION = 1

# Where the implementation script's path is: the third argument, after the two
# 'wrapper_common.handle_input()' spends on the run directory and the working
# directory -- as 'wrapper_simulate.SCRIPT_ARGUMENT' is, and for its reason.
SCRIPT_ARGUMENT = 3

LEVELS = ("error", "warning", "info")


def _failed(exception):
    return {"success": False, "exception": wrapper_common.exception_to_str(exception)}


def _findings(value):
    """What the plugin said it found, as findings PartCAD reads: anything else is dropped."""
    result = []
    for item in value or []:
        if isinstance(item, str):
            item = {"level": "info", "text": item}
        if not isinstance(item, dict) or not item.get("text"):
            continue
        level = item.get("level") if item.get("level") in LEVELS else "info"
        result.append({"level": level, "text": str(item["text"])})
    return result


def process(script, path, request):
    try:
        result = runpy.run_path(script, init_globals={"request": request, "path": path}, run_name="__partcad_qual__")
    except Exception as e:
        wrapper_common.handle_exception(e, script)
        return _failed(e)

    output = result.get("output")
    if output is None:
        entry_point = result.get("process")
        if not callable(entry_point):
            return _failed(
                Exception("%s: neither set 'output' nor defined 'process(path, request)'" % os.path.basename(script))
            )
        try:
            output = entry_point(path, request)
        except Exception as e:
            wrapper_common.handle_exception(e, script)
            return _failed(e)

    if not isinstance(output, dict):
        return _failed(Exception("%s: produced %s, expected a dict" % (os.path.basename(script), type(output))))

    exception = wrapper_common.exception_to_str(output.get("exception"))
    if exception is not None or output.get("success") is False:
        return {"success": False, "exception": exception or "the check failed without saying why"}

    passed = output.get("passed")
    answer = {
        "success": True,
        "exception": None,
        "passed": passed if isinstance(passed, bool) else None,
        "skipped": str(output["skipped"]) if output.get("skipped") else None,
        "findings": _findings(output.get("findings")),
    }
    if isinstance(output.get("report"), dict):
        answer["report"] = output["report"]
    highlights = []
    for item in output.get("highlights") or []:
        if not isinstance(item, dict) or not item.get("file"):
            continue
        file = item["file"] if os.path.isabs(item["file"]) else os.path.join(path, item["file"])
        if not os.path.isfile(file):
            continue
        highlights.append(
            {
                "name": str(item.get("name") or os.path.splitext(os.path.basename(file))[0]),
                "kind": item.get("kind") if item.get("kind") in ("face", "edge", "volume") else "face",
                "file": os.path.abspath(file),
            }
        )
    if highlights:
        answer["highlights"] = highlights
    return answer


def main():
    """Answer the one request on standard input."""
    # Read raw: nothing in the request is geometry.
    path, request = wrapper_common.handle_input(decode=False)
    os.makedirs(path, exist_ok=True)
    script = sys.argv[SCRIPT_ARGUMENT] if len(sys.argv) > SCRIPT_ARGUMENT else None
    process_tree.lead_a_group()
    try:
        if script is None:
            result = _failed(Exception("No implementation script was passed to the qualification wrapper"))
        else:
            result = process(script, path, request)
        wrapper_common.handle_output(result)
    finally:
        process_tree.stop_started()


if __name__ == "__main__":
    main()
