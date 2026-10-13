#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for a simulation plugin.

The counterpart of 'wrapper_export.py' for the ``simulation:`` section: every
simulation PartCAD runs is a Python script run through here, inside a PartCAD
sandbox with whatever that plugin declared it needs. Every one of them comes
from a package: PartCAD implements no simulator (see 'partcad.output.SIMULATE'),
and 'partcad/partcad-sim-mujoco' is the MuJoCo one.

The contract is deliberately narrow, and it is the whole of what a simulation
plugin is:

  **a scene with the subject in it goes in, JSON comes out.**

The scene arrives as a *file* rather than as geometry, in the format the plugin
declared with ``format:`` -- ``mjcf`` for the MuJoCo plugin -- because a
simulator reads its own model format and PartCAD already knows how to write
several. That also keeps the plugin free of OCP: it is handed a path, and what
it does with it is its own business.

The script is executed with these globals available:

    request  -- ``scene_file`` (the absolute path of the exported scene),
                ``scene_format``, ``scene_name``, ``subject`` (the full path of
                the object being simulated) and ``subject_kind``, plus every
                parameter declared for this plugin (see the plugin package's
                own 'partcad.yaml')
    path     -- an existing directory the run may write artifacts into (a
                trajectory, a video, a log). Nothing has to be written there;
                it exists so that a plugin that produces one has somewhere to
                put it that is neither the package nor a temporary directory
                nobody can find afterwards.

and reports what happened in one of two ways, whichever suits it:

    output = {"success": True, "before": {...}, "after": {...}}
    output = {"success": False, "exception": "..."}

or by defining a function, which is called with the same two values:

    def process(path, request): ...             # returns the dict above

``before`` and ``after`` are required of every plugin and are the only thing
PartCAD knows about the result: they are what a ``validation:`` expression is
handed. *What is inside them* is the plugin's own vocabulary -- the MuJoCo
plugin states where every body ended up, another might state a temperature
field -- and so is anything else the result carries beside them. PartCAD
neither reads nor validates the contents; it carries them to the expression and
reports what that says.

**Snapshots.** The request also carries ``snapshot``: two pictures of the scene
PartCAD would like, one as it was before anything moved and one as it is when
the run is over, and where to take them from::

    request["snapshot"] = {
        "format": "png",
        "files": {"before": "snapshot-before.png", "after": "snapshot-after.png"},
        "width": 512, "height": 512,
        "viewport_origin": [100, -100, 100],   # looked at from this direction
        "viewport_up": [0, 0, 1],              # and this way up in the picture
    }

The viewpoint is the scene's own -- what its ``render: png:`` configuration
says, as for ``pc render`` -- and means what it means there: a direction to look
from towards the middle of the scene, the picture scaled to fit. Each file is
named relative to ``path``. A plugin that draws them says so in its result::

    output = {..., "snapshots": {"before": "snapshot-before.png", "after": "snapshot-after.png"}}

They are optional. A plugin that cannot draw on this machine, or does not try,
reports none and the run is exactly as good: the verdict never depends on a
picture. They are what the IDE's Simulation tab shows, side by side.

Both '__file__' and the run name '__partcad_simulate__' are set on the script,
so it can gate any top-level work ("if __name__ == '__partcad_simulate__':")
and remain importable by its siblings.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# The key the request carries the implementation script under. Passed in the
# request rather than on the command line for the reason 'wrapper_export' gives:
# 'wrapper_common.handle_input()' already spends both positional arguments.
SCRIPT_KEY = "__script__"

# What a plugin's result has to carry. Everything else in it is the plugin's
# own, and is passed through untouched.
REQUIRED_KEYS = ("before", "after")


def _failed(exception):
    return {"success": False, "exception": wrapper_common.exception_to_str(exception)}


def process(script, path, request):
    try:
        result = runpy.run_path(
            script,
            init_globals={"request": request, "path": path},
            run_name="__partcad_simulate__",
        )
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

    # A script that reports an exception but forgets to clear 'success', or that
    # reports neither, is normalized here so the core only ever sees the two
    # consistent shapes.
    exception = wrapper_common.exception_to_str(output.get("exception"))
    succeeded = bool(output.get("success")) and exception is None
    if succeeded:
        missing = [key for key in REQUIRED_KEYS if not isinstance(output.get(key), dict)]
        if missing:
            # Reported here rather than left to the validation expression, which
            # would fail with a NameError that says nothing about whose fault it
            # is. A plugin that reports no 'before' and 'after' has not run a
            # simulation as far as PartCAD is concerned.
            return _failed(
                Exception(
                    "%s: a simulation result must carry '%s' as objects; %s"
                    % (
                        os.path.basename(script),
                        "' and '".join(REQUIRED_KEYS),
                        ", ".join("'%s' is missing or is not one" % key for key in missing),
                    )
                )
            )

    result = {"success": succeeded, "exception": exception}
    # Everything the plugin said, carried through as it is: 'before' and
    # 'after' because the validation expression is handed them, and the rest
    # because a plugin's own vocabulary is the point of having plugins.
    for key, value in output.items():
        if key not in ("success", "exception"):
            result[key] = value
    return result


def anchor(path, request):
    """Point the request's files at where they are on this side.

    The scene file is written into the run directory, and that directory is the
    first argument -- which a sandbox that sends files rather than sharing them
    rewrites to wherever it unpacked them. The request is one opaque string on
    standard input and is not rewritten, so the absolute path it names is the
    one on PartCAD's side, which does not exist here. The file is found again
    by its name under ``path``, where it is in either case.
    """
    scene_file = request.get("scene_file")
    if path and isinstance(scene_file, str) and not os.path.exists(scene_file):
        candidate = os.path.join(path, os.path.basename(scene_file))
        if os.path.exists(candidate):
            request["scene_file"] = candidate
    return request


if __name__ == "__main__":
    # Read raw: nothing here is geometry, and decoding would need OCP in a
    # sandbox that has no reason to carry it.
    path, request = wrapper_common.handle_input(decode=False)
    request = anchor(path, request)
    script = request.pop(SCRIPT_KEY, None)
    if script is None:
        result = _failed(Exception("No implementation script was passed to the simulation wrapper"))
    else:
        result = process(script, path, request)
    wrapper_common.handle_output(result)
