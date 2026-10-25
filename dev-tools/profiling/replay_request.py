#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Replay a request 'capture_request.py' captured, and say what each phase of the render costs.

    <sandbox python> dev-tools/profiling/replay_request.py CMD.json STDIN.json [--output PATH]

Run it with the sandbox's interpreter -- the one under ~/.partcad/sandbox that
renders, which has the CAD stack -- not PartCAD's own. It runs the wrapper's own
'__main__' (wrapper_export.py) on the captured request, exactly as the sandbox
would, with each step wrapped so that the peak RSS of the process is recorded
per phase (a thread samples it every 20 ms): reading and parsing the request,
decoding the tree, the projection, writing the SVG, parsing it back and
rasterizing it. '--output' sends the picture somewhere other than where the
capture says, so the checked-in one is not overwritten.

Linux only: the samples are '/proc/self/status'.
"""

import argparse
import json
import os
import sys
import threading
import time


def _rss_kb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1])
    return 0


class Phases:
    """The peak RSS seen in each phase, in the order the phases began."""

    def __init__(self):
        self.current = "start"
        self.peaks = {}
        self.began = {}
        self.order = []
        self.enter("start")
        threading.Thread(target=self._sample, daemon=True).start()

    def enter(self, name):
        self.current = name
        if name not in self.began:
            self.began[name] = time.time()
            self.order.append(name)
        self.peaks[name] = max(self.peaks.get(name, 0), _rss_kb())

    def _sample(self):
        while True:
            rss = _rss_kb()
            if rss > self.peaks.get(self.current, 0):
                self.peaks[self.current] = rss
            time.sleep(0.02)

    def report(self):
        end = time.time()
        for index, name in enumerate(self.order):
            until = self.began[self.order[index + 1]] if index + 1 < len(self.order) else end
            print("  %-38s peak %6d MB  %6.1fs" % (name, self.peaks.get(name, 0) // 1024, until - self.began[name]))
        print("  %-38s peak %6d MB  %6.1fs" % ("in all", max(self.peaks.values()) // 1024, end - self.began["start"]))


def _wrap(module, name, phases, before, after=None):
    original = getattr(module, name)

    def wrapped(*args, **kwargs):
        phases.enter(before)
        result = original(*args, **kwargs)
        if after is not None:
            phases.enter(after)
        return result

    setattr(module, name, wrapped)


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("cmd", help="the .cmd.json capture_request.py wrote")
    parser.add_argument("stdin", help="the .stdin.json capture_request.py wrote")
    parser.add_argument("--output", help="where to write the picture instead")
    args = parser.parse_args()

    phases = Phases()
    with open(args.cmd) as f:
        cmd = json.load(f)["cmd"]
    if args.output:
        cmd[1] = os.path.abspath(args.output)
    wrapper_path, script = cmd[0], cmd[3]
    sys.argv = list(cmd)
    sys.path.insert(0, os.path.dirname(wrapper_path))
    sys.path.insert(0, os.path.dirname(script))

    phases.enter("imports")
    import ocp_serialize  # noqa: F401 - first, for the expat pin it makes
    import render_raster
    import render_svg
    import wrapper_common
    import wrapper_export

    _wrap(wrapper_common, "handle_input", phases, "read and parse the request")
    _wrap(wrapper_export, "decode", phases, "decode the tree", "after decoding")
    _wrap(render_svg, "project_by_color", phases, "mesh and hidden-line removal", "edges to SVG")
    _wrap(render_raster.svglib, "svg2rlg", phases, "parse the SVG")
    _wrap(render_raster.renderPM, "drawToFile", phases, "rasterize", "done")

    with open(wrapper_path) as f:
        source = f.read()
    main_block = source[source.index('if __name__ == "__main__":') :]
    namespace = dict(vars(wrapper_export), __name__="__main__")
    stdin, stdout = sys.stdin, sys.stdout
    sys.stdin = open(args.stdin)
    sys.stdout = open(os.devnull, "w")
    try:
        exec(compile(main_block, wrapper_path, "exec"), namespace)
    finally:
        sys.stdin, sys.stdout = stdin, stdout
    phases.enter("done")
    # After the wrapper's own answer, which it writes to the descriptor it kept
    # for PartCAD (see 'wrapper_common.protect_response_channel'), unredirected.
    print("\n%s -> %s" % (os.path.basename(args.stdin), cmd[1]))
    phases.report()


if __name__ == "__main__":
    main()
