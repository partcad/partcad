#!/usr/bin/env python3
"""Print the subset of behave feature files that belong to one CI shard.

The behave suite is single-process and, run whole, dominates CI wall-clock. CI
splits it across several parallel jobs (a ``shard`` matrix axis) and hands each
job the file list this script prints. All feature files are always covered --
the shards only change how many run in parallel, not which run.

Balancing is by an estimated scenario count (a decent proxy for runtime): each
feature is weighed by its ``Scenario``/``Scenario Outline`` keywords plus the
data rows of its ``Examples`` tables, then assigned longest-first to whichever
shard is currently lightest (LPT greedy). This keeps the heavy feature files
(e.g. lint.feature, add/part.feature) from piling onto a single shard.

Usage::

    behave_shard.py --shards N --index I   # I is 1-based, 1 <= I <= N

Determinism: the file list is sorted before assignment, so the same
(shards, index) always yields the same files regardless of filesystem order.
"""

import argparse
import glob
import os
import re

_SCENARIO_RE = re.compile(r"^[ \t]*(Scenario|Scenario Outline):", re.MULTILINE)
_EXAMPLES_RE = re.compile(r"^[ \t]*Examples:", re.MULTILINE)


def _weight(path: str) -> int:
    """Estimate a feature file's runtime cost by scenario count."""
    try:
        with open(path, encoding="utf-8", errors="replace") as handle:
            text = handle.read()
    except OSError:
        return 1

    weight = len(_SCENARIO_RE.findall(text))

    # A Scenario Outline runs once per Examples data row, so count those rows
    # instead of the single "Scenario Outline:" line. Table rows start with a
    # pipe; the header row of each Examples block is not a scenario, so subtract
    # one row per Examples block.
    table_rows = sum(1 for line in text.splitlines() if line.lstrip().startswith("|"))
    examples_blocks = len(_EXAMPLES_RE.findall(text))
    weight += max(0, table_rows - examples_blocks)

    # Every feature has at least some fixed setup cost; never let it be zero, or
    # empty/comment-only files would all collapse onto one shard.
    return max(1, weight)


def _features_root() -> str:
    return os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "features")


def shard_files(shards: int, index: int):
    """Return the sorted feature files assigned to 1-based ``index`` of ``shards``."""
    root = _features_root()
    files = sorted(glob.glob(os.path.join(root, "**", "*.feature"), recursive=True))
    # Emit paths relative to the repo root so the CI command line stays short and
    # portable across the runner's working directory.
    repo_root = os.path.dirname(root)
    files = [os.path.relpath(path, repo_root) for path in files]

    # LPT greedy: assign the heaviest feature to the lightest shard so far.
    loads = [0] * shards
    buckets = [[] for _ in range(shards)]
    for path in sorted(files, key=lambda p: (-_weight(os.path.join(repo_root, p)), p)):
        target = min(range(shards), key=lambda s: loads[s])
        buckets[target].append(path)
        loads[target] += _weight(os.path.join(repo_root, path))

    # Keep each shard's own list sorted for stable, readable CI logs.
    return sorted(buckets[index - 1])


def main() -> int:
    parser = argparse.ArgumentParser(description="Print behave feature files for one CI shard.")
    parser.add_argument("--shards", type=int, required=True, help="Total number of shards.")
    parser.add_argument("--index", type=int, required=True, help="This shard's 1-based index.")
    parser.add_argument(
        "--sep",
        default=" ",
        help="Separator between file paths (default: space, for a shell command line).",
    )
    args = parser.parse_args()

    if args.shards < 1:
        parser.error("--shards must be >= 1")
    if not (1 <= args.index <= args.shards):
        parser.error("--index must be between 1 and --shards")

    print(args.sep.join(shard_files(args.shards, args.index)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
