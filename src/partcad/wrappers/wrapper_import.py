#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Sandbox entry point for an import plugin.

The mirror image of 'wrapper_export.py': that one turns a PartCAD object into a
file of somebody else's format, and this one turns such a file back into a
PartCAD object. Every reader PartCAD has is a Python script run through here,
inside a sandbox with whatever that reader declared it needs -- the ones that
ship with PartCAD ('builtin/import/') no differently from the ones a plugin
package supplies.

The contract is:

    **a file goes in, a tree of placed shapes comes out.**

What comes back is plain *data*, never geometry. A node names the file its
shape is read from and where that shape sits; the part factory for that file's
own format reads it afterwards, in its own runtime. The one exception is a
format's primitives -- a box, a cylinder, a sphere -- which have no file of
their own, so a reader writes them out (see 'primitive_shapes') and names the
file it wrote. That is what keeps a reader cheap: it parses XML and does
arithmetic, and it never has to know how to read a STEP.

The script is executed with these globals available:

    request  -- ``source_file`` (the absolute path of the file to read, already
                rendered as a Jinja2 template like every other source file),
                ``base_dir`` (the directory the package declared it in, which is
                what relative references inside the file resolve against),
                ``output_folder`` (where generated geometry goes), ``kind``
                ('assembly' or 'scene' -- some formats are read as either, and
                a reader may word its warnings accordingly) and ``object_name``,
                plus every parameter declared for this type
    path     -- an existing directory the run may write into

and reports what it read in one of two ways, whichever suits it:

    output = {"root": {...}}
    output = {"success": False, "exception": "..."}

or by defining a function, which is called with the same two values:

    def process(path, request): ...             # returns the dict above

``root`` is required and is the tree itself: a node with ``type``
('assembly' or 'part'), ``name``, ``location``, and either ``links`` (children)
or the ``part_file``/``part_type`` a part is read from. Beside it a reader may
report ``warnings`` (strings, logged as they are), ``dropped`` (a count per kind
of thing the format said that a static tree cannot hold -- the declaration's
``dropped:`` map is what words them) and ``model_name`` (what the file called
itself). Anything else is carried through untouched and reaches 'pc info'.

**Every reader is best-effort, and saying so is part of the contract.** These
formats describe machines that move and worlds that run; a PartCAD tree
describes where things are. What cannot survive that is counted in ``dropped``
rather than passed over in silence, which is why the count is part of the
result and not a log line.

Both '__file__' and the run name '__partcad_import__' are set on the script, so
it can gate any top-level work ("if __name__ == '__partcad_import__':") and
remain importable by its siblings.
"""

import os
import runpy
import sys

sys.path.append(os.path.dirname(__file__))
import wrapper_common

# The key the request carries the implementation script under. Passed in the
# request rather than on the command line for the reason 'wrapper_export' gives:
# 'wrapper_common.handle_input()' already spends both positional arguments.
SCRIPT_KEY = "__script__"


def _failed(exception):
    return {
        "success": False,
        "exception": wrapper_common.exception_to_str(exception),
        # So that a caller reading the tree off a failed result gets None rather
        # than a KeyError on top of whatever actually went wrong.
        "root": None,
    }


def process(script, path, request):
    try:
        result = runpy.run_path(
            script,
            init_globals={"request": request, "path": path},
            run_name="__partcad_import__",
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

    # Returning at all is what success means for a reader, so a result that says
    # nothing about it succeeded: it read the file and here is the tree. That is
    # deliberately unlike 'wrapper_simulate', where a plugin states 'success'
    # because a simulation can run to completion and still have nothing to
    # report. A reader says it failed by raising - which is caught above - or by
    # saying so, in either of the two ways below.
    exception = wrapper_common.exception_to_str(output.get("exception"))
    succeeded = output.get("success", True) is not False and exception is None
    if succeeded and not isinstance(output.get("root"), dict):
        # Reported here rather than left to the factory, which would walk a
        # None and complain about something further from the cause. A reader
        # that produced no tree has not read the file.
        return _failed(Exception("%s: reported no 'root' tree" % os.path.basename(script)))

    result = {"success": succeeded, "exception": exception, "root": output.get("root")}
    for key, value in output.items():
        if key not in ("success", "exception", "root"):
            result[key] = value
    return result


if __name__ == "__main__":
    # Read raw: the request is paths and parameters, and the tree that comes
    # back is data. Nothing here is an envelope to decode.
    path, request = wrapper_common.handle_input(decode=False)
    script = request.pop(SCRIPT_KEY, None)
    if script is None:
        result = _failed(Exception("No implementation script was passed to the import wrapper"))
    else:
        result = process(script, path, request)
    wrapper_common.handle_output(result)
