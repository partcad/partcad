#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Summarize what 'memory_sampler.py' recorded: the peaks, how much ran at once, and the jobs that cost most.

    memory_report.py SAMPLES.jsonl [--step SECONDS] [--top N]

Prints the peak of all PartCAD processes together (PSS), of the sandboxes
alone, and of the daemon; the lowest MemAvailable; every process at the moment
of the peak; each sandbox job's own peak and how long it ran; and a timeline.
Stdlib only.
"""

import argparse
import collections
import json


def _mb(kb):
    return (kb or 0) // 1024


def _size(process):
    return process["pss"] or process["rss"]


def main():
    parser = argparse.ArgumentParser(description=(__doc__ or "").split("\n\n")[0])
    parser.add_argument("samples", help="the JSON lines file memory_sampler.py wrote")
    parser.add_argument("--step", type=float, default=60, help="seconds between timeline rows (default 60)")
    parser.add_argument("--top", type=int, default=20, help="how many of the most expensive jobs to list")
    args = parser.parse_args()

    with open(args.samples) as f:
        rows = [json.loads(line) for line in f if line.strip()]
    if not rows:
        print("no samples")
        return

    # A process whose PSS could not be read (no smaps_rollup) is counted at its
    # RSS, which counts the libraries it shares with the others again: say so
    # wherever such a process is in a total.
    def _label(sandboxes_only):
        unread = {
            p["pid"]
            for row in rows
            for p in row["procs"]
            if p["pss"] is None and (p["role"] == "sandbox" or not sandboxes_only)
        }
        return "PSS" if not unread else "PSS, and RSS for %d processes whose PSS was unreadable" % len(unread)

    jobs = {}
    peak_total = peak_sandboxes = (0, rows[0])
    most_at_once = (0, rows[0])
    lowest = (None, rows[0])
    daemon_peak = 0
    timeline = []
    next_row = 0.0
    for row in rows:
        sandboxes = [p for p in row["procs"] if p["role"] == "sandbox"]
        total = sum(_size(p) for p in row["procs"])
        in_sandboxes = sum(_size(p) for p in sandboxes)
        daemon = max([p["rss"] for p in row["procs"] if p["role"] == "daemon"] or [0])
        daemon_peak = max(daemon_peak, daemon)
        if total > peak_total[0]:
            peak_total = (total, row)
        if in_sandboxes > peak_sandboxes[0]:
            peak_sandboxes = (in_sandboxes, row)
        if len(sandboxes) > most_at_once[0]:
            most_at_once = (len(sandboxes), row)
        if row.get("avail") is not None and (lowest[0] is None or row["avail"] < lowest[0]):
            lowest = (row["avail"], row)
        for process in sandboxes:
            job = jobs.setdefault(process["pid"], {"what": process["what"], "rss": 0, "first": row["t"]})
            job["rss"] = max(job["rss"], process["rss"])
            job["last"] = row["t"]
        if row["t"] >= next_row:
            timeline.append((row["t"], total, in_sandboxes, daemon, len(sandboxes), row.get("avail")))
            next_row = row["t"] + args.step

    print("samples: %d over %.0fs" % (len(rows), rows[-1]["t"]))
    print(
        "peak, every PartCAD process (%s): %d MB at t=%.0fs" % (_label(False), _mb(peak_total[0]), peak_total[1]["t"])
    )
    print(
        "peak, sandboxes alone (%s): %d MB at t=%.0fs" % (_label(True), _mb(peak_sandboxes[0]), peak_sandboxes[1]["t"])
    )
    print("peak, daemon (RSS): %d MB" % _mb(daemon_peak))
    if lowest[0] is not None:
        print("lowest MemAvailable: %d MB at t=%.0fs" % (_mb(lowest[0]), lowest[1]["t"]))
    print("most sandboxes at once: %d at t=%.0fs" % (most_at_once[0], most_at_once[1]["t"]))

    print("\nat the peak (t=%.0fs):" % peak_total[1]["t"])
    for process in sorted(peak_total[1]["procs"], key=lambda p: -_size(p)):
        print(
            "  %-8s rss %6d MB  pss %6s MB  %s"
            % (
                process["role"],
                _mb(process["rss"]),
                "?" if process["pss"] is None else _mb(process["pss"]),
                process["what"][:90],
            )
        )

    by_wrapper = collections.defaultdict(list)
    for job in jobs.values():
        by_wrapper[job["what"].split(" ")[0]].append(job)
    print(
        "\nsandbox jobs: "
        + ", ".join(
            "%s x%d (largest %d MB)" % (name, len(group), _mb(max(j["rss"] for j in group)))
            for name, group in sorted(by_wrapper.items())
        )
    )
    print("\nthe %d most expensive (peak RSS, time running):" % args.top)
    for job in sorted(jobs.values(), key=lambda j: -j["rss"])[: args.top]:
        print("  %6d MB  %6.0fs  %s" % (_mb(job["rss"]), job["last"] - job["first"], job["what"][:110]))

    print("\ntimeline: t, every process MB, sandboxes MB, daemon MB, sandboxes, MemAvailable MB")
    for t, total, in_sandboxes, daemon, count, available in timeline:
        print("  %6.0f %7d %7d %6d %3d %7d" % (t, _mb(total), _mb(in_sandboxes), _mb(daemon), count, _mb(available)))


if __name__ == "__main__":
    main()
