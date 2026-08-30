#!/usr/bin/env python3
"""Print the subset of behave feature files that belong to one CI shard.

The behave suite is single-process and, run whole, dominates CI wall-clock. CI
splits it across several parallel jobs (a ``shard`` matrix axis) and hands each
job the file list this script prints. All feature files are always covered --
the shards only change how many run in parallel, not which run.

Balancing is by *measured* runtime: ``behave_durations.json`` holds how long each
feature file actually took in CI, and features are assigned longest-first to
whichever shard is currently lightest (LPT greedy).

Measured seconds rather than a scenario count, because the two are barely
related. A scenario that runs ``pc export`` builds geometry through a CAD kernel
and takes a minute or more; a scenario that runs ``pc list`` takes under a
second; and a feature tagged ``@wip`` is excluded by ``behave.ini`` and takes
none at all. Counting scenarios made ``inspect.feature`` (36 scenarios, all
``@wip``, 0.1s) the single heaviest file in the suite and ``export.feature``
(9 scenarios, 18 minutes) one of the lightest, so the shards came out balanced
on paper and 3x apart in reality.

A feature file with no measurement -- a newly added one -- is estimated instead,
from its scenario count times the median measured cost of a scenario, so it is
never treated as free. ``@wip`` at the feature level estimates to zero, matching
what ``behave.ini`` does with it.

Usage::

    behave_shard.py --shards N --index I   # I is 1-based, 1 <= I <= N
    behave_shard.py --shards N --summary   # per-shard predicted load, all shards

Determinism: assignment is over a sorted file list with a total order on ties, so
the same (shards, index) always yields the same files regardless of filesystem
order.
"""

import argparse
import glob
import json
import os
import re

_SCENARIO_RE = re.compile(r"^[ \t]*(Scenario|Scenario Outline):", re.MULTILINE)
_EXAMPLES_RE = re.compile(r"^[ \t]*Examples:", re.MULTILINE)

# Tags on the ``Feature:`` line itself apply to every scenario in the file.
# ``behave.ini`` runs with ``tags = ~@wip``, so such a file contributes nothing.
_FEATURE_RE = re.compile(r"^[ \t]*Feature:", re.MULTILINE)
_TAG_RE = re.compile(r"@[\w.-]+")

_EXCLUDED_TAGS = frozenset({"@wip"})

# Median seconds per scenario over the measured features that actually run. Used
# only to estimate a feature file that has no measurement yet; see _weight().
_SECONDS_PER_SCENARIO = 3.3

_DURATIONS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "behave_durations.json")


def measured_durations() -> dict:
    """Return the measured seconds per feature file, or {} if unavailable."""
    try:
        with open(_DURATIONS_FILE, encoding="utf-8") as handle:
            return dict(json.load(handle).get("seconds", {}))
    except (OSError, ValueError):
        # Never let a missing or malformed table stop CI from producing a split:
        # every feature falls back to the estimate below, which is worse but
        # still covers every file exactly once.
        return {}


def _read(path: str) -> str:
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            return handle.read()
    except OSError:
        return ""


def _feature_tags(text: str) -> set:
    """Tags attached to the ``Feature:`` keyword (the lines just above it)."""
    match = _FEATURE_RE.search(text)
    if not match:
        return set()
    tags = set()
    for line in reversed(text[: match.start()].splitlines()):
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if not stripped.startswith("@"):
            break
        tags.update(_TAG_RE.findall(stripped))
    return tags


def _estimate(path: str) -> float:
    """Estimate an unmeasured feature file's runtime from its scenario count."""
    text = _read(path)
    if _feature_tags(text) & _EXCLUDED_TAGS:
        return 0.0

    scenarios = len(_SCENARIO_RE.findall(text))

    # A Scenario Outline runs once per Examples data row, so count those rows
    # instead of the single "Scenario Outline:" line. Table rows start with a
    # pipe; the header row of each Examples block is not a scenario, so subtract
    # one row per Examples block.
    table_rows = sum(1 for line in text.splitlines() if line.lstrip().startswith("|"))
    examples_blocks = len(_EXAMPLES_RE.findall(text))
    scenarios += max(0, table_rows - examples_blocks)

    return max(1, scenarios) * _SECONDS_PER_SCENARIO


def _weight(path: str, durations: dict, rel: str) -> float:
    """Seconds this feature file is expected to cost the shard that runs it."""
    if rel in durations:
        return float(durations[rel])
    return _estimate(path)


def _features_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "features")


def _feature_files():
    """Every feature file, as a repo-root-relative POSIX path, sorted."""
    root = _features_root()
    repo_root = os.path.dirname(root)
    # Emit paths relative to the repo root so the CI command line stays short and
    # portable across the runner's working directory.
    files = [
        os.path.relpath(path, repo_root).replace(os.sep, "/")
        for path in glob.glob(os.path.join(root, "**", "*.feature"), recursive=True)
    ]
    return repo_root, sorted(files)


def shard_loads(shards: int):
    """Return (buckets, loads): the files per 1-based shard and their seconds."""
    repo_root, files = _feature_files()
    durations = measured_durations()
    weights = {rel: _weight(os.path.join(repo_root, rel), durations, rel) for rel in files}

    # LPT greedy: assign the heaviest feature to the lightest shard so far. The
    # path is the tie-breaker, so equal weights order the same way every run.
    loads = [0.0] * shards
    buckets = [[] for _ in range(shards)]
    for rel in sorted(files, key=lambda p: (-weights[p], p)):
        target = min(range(shards), key=lambda s: (loads[s], s))
        buckets[target].append(rel)
        loads[target] += weights[rel]

    # Keep each shard's own list sorted for stable, readable CI logs.
    return [sorted(bucket) for bucket in buckets], loads


def shard_files(shards: int, index: int):
    """Return the sorted feature files assigned to 1-based ``index`` of ``shards``."""
    return shard_loads(shards)[0][index - 1]


def main() -> int:
    parser = argparse.ArgumentParser(description="Print behave feature files for one CI shard.")
    parser.add_argument("--shards", type=int, required=True, help="Total number of shards.")
    parser.add_argument("--index", type=int, help="This shard's 1-based index.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print every shard's predicted load instead of one shard's files.",
    )
    parser.add_argument(
        "--sep",
        default=" ",
        help="Separator between file paths (default: space, for a shell command line).",
    )
    args = parser.parse_args()

    if args.shards < 1:
        parser.error("--shards must be >= 1")
    if args.summary:
        buckets, loads = shard_loads(args.shards)
        for i, (bucket, load) in enumerate(zip(buckets, loads), start=1):
            print("shard %d/%d: %d features, %.1f min predicted" % (i, args.shards, len(bucket), load / 60.0))
        print("worst shard: %.1f min predicted" % (max(loads) / 60.0))
        return 0
    if args.index is None:
        parser.error("--index is required unless --summary is given")
    if not (1 <= args.index <= args.shards):
        parser.error("--index must be between 1 and --shards")

    print(args.sep.join(shard_files(args.shards, args.index)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
