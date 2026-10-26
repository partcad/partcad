#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Record the memory of every PartCAD process on this machine, as JSON lines, until stopped.

    memory_sampler.py OUT.jsonl [--interval SECONDS]

Each line is one sample: the seconds since the sampler started, the system's
MemAvailable and swap, the memory the sampler's own cgroup uses (when there is
one), and every PartCAD process -- the daemon, the client, each sandbox -- with
its RSS and PSS in kB and, for a sandbox, which wrapper it runs and which file
or object it is working on, read off its command line.

PSS is what to add up: four sandbox interpreters share the same CAD libraries,
and their RSS counts those four times. It needs '/proc/<pid>/smaps_rollup'
(Linux), and the sampler falls back to RSS where there is none.

Stdlib only, and Linux only: what it reads is '/proc' and the cgroup tree. Start
it beside a command, stop it when the command ends, and read the result with
'memory_report.py'. See README.md.
"""

import argparse
import json
import os
import time


def _read(path):
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return None


def _meminfo():
    info = {}
    with open("/proc/meminfo") as f:
        for line in f:
            key, value = line.split(":", 1)
            info[key] = int(value.split()[0])
    return info


def _cgroup_files():
    """The files saying how much memory this process's cgroup uses now and at most, or (None, None)."""
    text = (_read("/proc/self/cgroup") or b"").decode(errors="replace")
    for line in text.splitlines():
        _id, controllers, path = line.split(":", 2)
        if controllers == "memory":  # cgroup v1
            base = "/sys/fs/cgroup/memory" + path
            return base + "/memory.usage_in_bytes", base + "/memory.max_usage_in_bytes"
        if controllers == "":  # cgroup v2
            base = "/sys/fs/cgroup" + path
            if os.path.exists(base + "/memory.current"):
                return base + "/memory.current", base + "/memory.peak"
    return None, None


def _kb(path):
    data = _read(path) if path else None
    return int(data) // 1024 if data and data.strip().isdigit() else None


def classify(argv):
    """('daemon' | 'client' | 'sandbox', what it works on), or (None, None) for anything else."""
    joined = " ".join(argv)
    if "partcad_service_json_rpc" in joined or "partcad-json-rpc" in joined:
        return "daemon", ""
    for index, arg in enumerate(argv):
        name = os.path.basename(arg)
        if name.startswith("wrapper_") and name.endswith((".py", ".mjs")):
            return "sandbox", " ".join([name] + [os.path.basename(a) for a in argv[index + 1 : index + 4]])
    if any(os.path.basename(arg) in ("pc", "partcad") for arg in argv[:3]):
        return "client", joined[:160]
    return None, None


def sample():
    processes = []
    for pid in os.listdir("/proc"):
        if not pid.isdigit():
            continue
        raw = _read("/proc/%s/cmdline" % pid)
        if not raw:
            continue
        argv = [arg.decode(errors="replace") for arg in raw.split(b"\0") if arg]
        role, what = classify(argv)
        if role is None:
            continue
        rss = ppid = 0
        for line in (_read("/proc/%s/status" % pid) or b"").decode(errors="replace").splitlines():
            if line.startswith("VmRSS:"):
                rss = int(line.split()[1])
            elif line.startswith("PPid:"):
                ppid = int(line.split()[1])
        pss = None
        for line in (_read("/proc/%s/smaps_rollup" % pid) or b"").decode(errors="replace").splitlines():
            if line.startswith("Pss:"):
                pss = int(line.split()[1])
                break
        processes.append({"pid": int(pid), "ppid": ppid, "rss": rss, "pss": pss, "role": role, "what": what})
    return processes


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("output", help="the JSON lines file to append to")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between samples (default 1)")
    args = parser.parse_args()

    usage, peak = _cgroup_files()
    start = time.time()
    with open(args.output, "a", buffering=1) as out:
        while True:
            info = _meminfo()
            out.write(
                json.dumps(
                    {
                        "t": round(time.time() - start, 1),
                        "avail": info.get("MemAvailable"),
                        "swap_free": info.get("SwapFree"),
                        "swap_total": info.get("SwapTotal"),
                        "cg": _kb(usage),
                        "cgpeak": _kb(peak),
                        "procs": sample(),
                    }
                )
                + "\n"
            )
            time.sleep(args.interval)


if __name__ == "__main__":
    main()
