#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Capture the exact request PartCAD sends a sandbox to render one object, and say what it is made of.

    poetry --project <partcad checkout> run python capture_request.py OUTDIR OBJECT [FILE_TYPE]

Run from the package the object belongs to, with PartCAD's own interpreter. It renders OBJECT to FILE_TYPE
('png' when not given) in this process, intercepts the one sandbox launch of
'wrapper_export.py', writes the command and the request to
OUTDIR/<object>.<type>.cmd.json and .stdin.json, and answers PartCAD with a
success so nothing is drawn. 'replay_request.py' runs what it wrote.

It also reports the tree: how many nodes and leaves, how many distinct BREP
payloads by content, their compressed size against the size of all the leaves
together, and how large the request is serialized.

Builds what the object is made of if it is not cached yet, through the same
sandboxes 'pc' would use.
"""

import argparse
import asyncio
import hashlib
import json
import os
import resource


def _rss_mb():
    with open("/proc/self/status") as f:
        for line in f:
            if line.startswith("VmRSS:"):
                return int(line.split()[1]) // 1024
    return 0


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("outdir")
    parser.add_argument("object", help="the object, as named in its package")
    parser.add_argument("file_type", nargs="?", default="png")
    args = parser.parse_args()
    os.makedirs(args.outdir, exist_ok=True)

    import partcad as pc
    from partcad import runtime_python, shape_envelope

    base = os.path.join(args.outdir, "%s.%s" % (args.object.replace("/", "_").replace(":", "_"), args.file_type))
    captured = {}
    original = runtime_python.PythonRuntime.run_async

    async def intercept(self, cmd, stdin="", cwd=None, session=None, timeout=None):
        if cmd and os.path.basename(cmd[0]) == "wrapper_export.py":
            text = stdin() if callable(stdin) else stdin
            text = text.decode("utf-8") if isinstance(text, bytes) else text
            captured["request"] = len(text)
            with open(base + ".cmd.json", "w") as f:
                json.dump({"cmd": cmd}, f)
            with open(base + ".stdin.json", "w") as f:
                f.write(text)
            return 0, json.dumps({"success": True, "exception": None}), ""
        return await original(self, cmd, stdin=stdin, cwd=cwd, session=session, timeout=timeout)

    runtime_python.PythonRuntime.run_async = intercept

    ctx = pc.init(".")
    project = ctx.get_project(ctx.get_current_project_path())
    kind = project.object_kind(args.object)
    getter = {"part": project.get_part, "sketch": project.get_sketch, "scene": project.get_scene}
    shape = getter.get(kind, project.get_assembly)(args.object)
    if shape is None:
        raise SystemExit("%s: no object %r in the package here (%s)" % (parser.prog, args.object, project.name))
    tree = asyncio.run(shape.get_wrapped(ctx))

    nodes = leaves = leaf_bytes = 0
    objects = set()
    distinct = {}

    def walk(node):
        nonlocal nodes, leaves, leaf_bytes
        nodes += 1
        payload = node.get(shape_envelope.KEY_BREP)
        if payload is not None:
            leaves += 1
            leaf_bytes += len(payload)
            objects.add(id(payload))
            distinct.setdefault(hashlib.sha256(payload).hexdigest(), len(payload))
        for child in node.get(shape_envelope.KEY_ASSEMBLY) or []:
            walk(child)

    walk(tree)
    print("%s %s: %d nodes, %d leaves" % (kind, args.object, nodes, leaves))
    print(
        "payloads: %d distinct by content (%d objects in memory), %.1f MB of them against %.1f MB in all the leaves"
        % (len(distinct), len(objects), sum(distinct.values()) / 1e6, leaf_bytes / 1e6)
    )

    asyncio.run(
        project.render_async(
            assemblies=[args.object] if kind == "assembly" else None,
            parts=[args.object] if kind == "part" else None,
            sketches=[args.object] if kind == "sketch" else None,
            scenes=[args.object] if kind == "scene" else None,
            format=args.file_type,
        )
    )
    if "request" not in captured:
        print("no sandbox was asked to render it; is %s a file type of this package?" % args.file_type)
        return
    print("request: %.1f MB, written to %s.stdin.json" % (captured["request"] / 1e6, base))
    print("peak RSS of this process: %d MB" % (resource.getrusage(resource.RUSAGE_SELF).ru_maxrss // 1024))


if __name__ == "__main__":
    main()
