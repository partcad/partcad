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

**Video.** The request carries ``video`` too, unless this machine's
configuration asks for none: a video of the whole run, from the same viewpoint
as the pictures, a frame every 1/fps seconds of *simulated* time from the start
of the run to its end -- so that it plays the run in real time::

    request["video"] = {
        "format": "webm",                      # WebM, with VP9 in it
        "file": "video.webm",
        "fps": 25,
        "width": 1280, "height": 720,          # 'simulation.videoResolution'
        "viewport_origin": [100, -100, 100],   # the snapshots' own
        "viewport_up": [0, 0, 1],
    }

The file is named relative to ``path``, as the pictures are, and a plugin that
recorded it says so in its result::

    output = {..., "video": "video.webm"}

It is as optional as the pictures, and for the same reason. The IDE's
Simulation tab plays it, with the two pictures as the still it shows until it
is played. A plugin draws it inside the run's budget, below, and one that would
not finish it in time is better off giving it up, with a warning, than losing
the run's answer to the watchdog.

Both '__file__' and the run name '__partcad_simulate__' are set on the script,
so it can gate any top-level work ("if __name__ == '__partcad_simulate__':")
and remain importable by its siblings.

**The run's budget.** ``request["timeout"]`` is how long the whole run may take,
in wall-clock seconds from when this wrapper starts; PartCAD works it out (see
'partcad.simulation.run_budget') and hands it to the plugin as it hands every
other parameter. When it is spent, this wrapper answers for the plugin --
``{"success": False, "timed_out": <seconds>, ...}`` -- stops everything the
plugin started and exits with 124, the status coreutils' ``timeout`` uses. It is
here, inside the sandbox, rather than only in PartCAD, because PartCAD may not
be able to reach what is running: in the ``docker`` sandbox all it started is a
``docker exec`` client (see 'process_tree.py'). PartCAD keeps a bound of its own
a little longer than this one, for a run so wedged that this one cannot act.

A plugin that wants to say more than "timed out" -- how far it got, what it was
waiting for -- stops itself a little before the budget is spent, and reports
that as its own ``exception``.

Whatever the plugin leaves running when it returns is stopped too, on every way
out: a process that outlives the run holds its output open, and PartCAD would
wait for it as for a run that never finished.
"""

import math
import os
import runpy
import sys
import threading

sys.path.append(os.path.dirname(__file__))
import process_tree
import wrapper_common

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 1

# Where the implementation script's path is: the third argument, after the two
# 'wrapper_common.handle_input()' spends on the run directory and the working
# directory -- as 'wrapper_export.SCRIPT_ARGUMENT' is, and for its reason. A
# sandbox that sends files rather than sharing them unpacks the directories
# somewhere of its own choosing and rewrites every argument naming one; the
# request is one opaque string on standard input and is not rewritten. It was
# carried there, and in upload mode it named the plugin's script where it is on
# PartCAD's side, which is nowhere in the container: "[Errno 2] No such file or
# directory: '.../simulate_gazebo.py'".
SCRIPT_ARGUMENT = 3

# What a plugin's result has to carry. Everything else in it is the plugin's
# own, and is passed through untouched.
REQUIRED_KEYS = ("before", "after")

# The request's key for the run's budget, in wall-clock seconds; see the
# docstring above. 'partcad.simulation.TIMEOUT_KEY' is its twin.
TIMEOUT_KEY = "timeout"

# The result's key a spent budget is reported under, carrying the seconds.
# 'partcad.simulation.TIMED_OUT_KEY' is its twin.
TIMED_OUT_KEY = "timed_out"

# The exit status of a run stopped because its budget was spent: the one
# coreutils' 'timeout' exits with, so that whoever reads only the status still
# reads it as what it is.
TIMED_OUT_EXIT = 124


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


def budget_of(request):
    """The run's budget in seconds, or None when the request states none that is one."""
    value = request.get(TIMEOUT_KEY) if isinstance(request, dict) else None
    if isinstance(value, bool):
        return None
    try:
        value = float(value)
    except (TypeError, ValueError):
        return None
    return value if math.isfinite(value) and value > 0 else None


def timed_out(seconds):
    """The answer given for a plugin whose budget was spent."""
    return {
        "success": False,
        "exception": "the plugin did not finish within its budget of %g s, and was stopped with everything it started"
        % seconds,
        TIMED_OUT_KEY: seconds,
    }


class Answer:
    """The one answer this process gives: the run's, or the watchdog's, whichever is first."""

    def __init__(self):
        self._lock = threading.Lock()
        self._given = False

    def give(self, result):
        """Write 'result' as the answer; False, and nothing written, if one was already given."""
        with self._lock:
            if self._given:
                return False
            self._given = True
        wrapper_common.handle_output(result)
        return True


def watch(seconds, answer):
    """Answer for the run, and stop it, once 'seconds' have passed. Returns the timer.

    A thread, so it acts whatever the plugin is doing -- stepping a model,
    waiting on a pipe, sleeping -- short of holding the interpreter in native
    code, which is what PartCAD's own, longer bound is for.
    """

    def expire():
        if answer.give(timed_out(seconds)):
            process_tree.stop_everything(TIMED_OUT_EXIT)

    timer = threading.Timer(seconds, expire)
    timer.daemon = True
    timer.start()
    return timer


def main():
    """Answer the one request on standard input, within its budget."""
    # Read raw: nothing here is geometry, and decoding would need OCP in a
    # sandbox that has no reason to carry it.
    path, request = wrapper_common.handle_input(decode=False)
    request = anchor(path, request)
    script = sys.argv[SCRIPT_ARGUMENT] if len(sys.argv) > SCRIPT_ARGUMENT else None
    answer = Answer()
    budget = budget_of(request)
    # Before the plugin starts anything, so that everything it starts is in
    # this process's group and can be found again.
    process_tree.lead_a_group()
    timer = watch(budget, answer) if budget is not None else None
    try:
        if script is None:
            result = _failed(Exception("No implementation script was passed to the simulation wrapper"))
        else:
            result = process(script, path, request)
        if not answer.give(result):
            # The budget ran out first and the watchdog has answered; it is
            # stopping everything, this thread included.
            threading.Event().wait()
        if timer is not None:
            timer.cancel()
    finally:
        # Whatever the plugin left running, so that nothing outlives the run
        # holding its output open -- on the way out of a run that raised, too.
        process_tree.stop_started()


if __name__ == "__main__":
    main()
