#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The behave suite is split across CI jobs by `dev-tools/behave_shard.py`. This
checks that the split still covers everything and is still even.

The split used to be balanced by scenario count, which is close to unrelated to
runtime: a `pc export` scenario drives a CAD kernel for a minute or more, a
`pc list` scenario takes under a second, and a `@wip` feature is excluded by
`behave.ini` and takes none at all. So the shards came out equal on paper --
81 weight each -- and 18, 24, 36 and 55 minutes of features in fact, and the
55 minute one was cancelled at the 60 minute job timeout on windows-latest
(CI run 33149121989, job 98776791432).

They are balanced by measured seconds now, from `behave_durations.json`. That
table is a snapshot, so the two ways it goes wrong are both checked here: a
feature file renamed or deleted leaves an entry pointing at nothing, and a
feature file added has no entry and gets estimated instead of measured. Neither
is fatal to CI -- an unmeasured feature is estimated from its scenario count --
but both quietly erode the balance, so both are caught at the point they happen
rather than at the timeout months later.
"""

import importlib.util
import json
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[3]
DEV_TOOLS = REPO_ROOT / "dev-tools"
DURATIONS = DEV_TOOLS / "behave_durations.json"

# The number of shards CI actually uses. Kept as a literal rather than parsed out
# of the workflow: this asserts the split is even at the size it ships at, and a
# change to BEHAVE_SHARDS should come here to say what the new size costs.
CI_SHARDS = 4

# The `timeout-minutes` on the Behave job, and what a shard has to fit inside
# once job setup is paid. Setup measured at 5.3-6.3 minutes across the
# windows-latest shards of run 33149121989.
JOB_TIMEOUT_MINUTES = 60
JOB_SETUP_MINUTES = 7


def _load_behave_shard():
    """Import `dev-tools/behave_shard.py`, which is a script, not a package."""
    spec = importlib.util.spec_from_file_location("behave_shard", DEV_TOOLS / "behave_shard.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


behave_shard = _load_behave_shard()


def _feature_files():
    return behave_shard._feature_files()[1]


def test_every_feature_runs_exactly_once():
    """Sharding changes how many features run in parallel, never which run."""
    buckets, _ = behave_shard.shard_loads(CI_SHARDS)
    assigned = [path for bucket in buckets for path in bucket]

    assert len(assigned) == len(set(assigned)), "a feature file is in more than one shard"
    assert sorted(assigned) == sorted(_feature_files()), "the shards do not cover every feature file"


@pytest.mark.parametrize("shards", [1, 2, 3, 4, 5, 8])
def test_split_covers_everything_at_any_shard_count(shards):
    """BEHAVE_SHARDS is a knob; no value of it may drop or duplicate a feature."""
    buckets, loads = behave_shard.shard_loads(shards)

    assert len(buckets) == shards
    assert len(loads) == shards
    assigned = [path for bucket in buckets for path in bucket]
    assert sorted(assigned) == sorted(_feature_files())


def test_shards_are_balanced_by_measured_runtime():
    """No shard may sit near the job timeout, and none may carry twice another.

    The balance is what the timeout depends on. A split whose worst shard is far
    from its best is the failure that was cancelled in CI, showing up here as a
    ratio rather than as a 60 minute job.
    """
    _, loads = behave_shard.shard_loads(CI_SHARDS)
    worst = max(loads) / 60.0
    best = min(loads) / 60.0

    budget = JOB_TIMEOUT_MINUTES - JOB_SETUP_MINUTES
    assert worst < budget, "the heaviest shard (%.1f min of features) does not fit in %d min of job time" % (
        worst,
        budget,
    )
    # LPT on this suite lands all four within a few seconds of each other. 1.5x
    # is loose enough that adding a feature never trips it and tight enough that
    # a weighting that stopped tracking reality does.
    assert worst <= best * 1.5, "shards are lopsided: %.1f min worst against %.1f min best" % (worst, best)


def test_measured_durations_name_features_that_exist():
    """A renamed or deleted feature must not leave a measurement behind.

    A stale entry is invisible -- it weighs a file that is never run -- so the
    balance silently degrades. Renaming a feature means moving its entry.
    """
    measured = set(json.loads(DURATIONS.read_text(encoding="utf-8"))["seconds"])
    stale = sorted(measured - set(_feature_files()))

    assert not stale, "dev-tools/behave_durations.json names feature files that no longer exist: %s" % ", ".join(stale)


def test_every_feature_has_a_measurement():
    """A new feature is estimated, not measured, which is a worse split.

    Not fatal -- `_estimate()` keeps it from being weighed as free -- but the
    estimate is a scenario count, and this suite has shown scenario counts to be
    off by two orders of magnitude. Add the feature to the table with a rough
    measurement; the numbers only have to be right relative to each other.
    """
    measured = set(json.loads(DURATIONS.read_text(encoding="utf-8"))["seconds"])
    unmeasured = sorted(set(_feature_files()) - measured)

    assert not unmeasured, (
        "these feature files have no entry in dev-tools/behave_durations.json, so CI has to guess "
        "what they cost: %s" % ", ".join(unmeasured)
    )


def test_wip_features_are_estimated_as_free(tmp_path):
    """`behave.ini` runs `tags = ~@wip`, so a @wip feature costs nothing.

    This is what made `inspect.feature` -- 36 scenarios, every one of them
    skipped -- the heaviest file in the suite under the old weighting.
    """
    wip = tmp_path / "wip.feature"
    wip.write_text(
        "@wip @cli\nFeature: skipped entirely\n  Scenario: one\n  Scenario: two\n  Scenario: three\n",
        encoding="utf-8",
    )
    live = tmp_path / "live.feature"
    live.write_text(
        "@cli\nFeature: actually runs\n  Scenario: one\n  Scenario: two\n  Scenario: three\n",
        encoding="utf-8",
    )

    assert behave_shard._estimate(str(wip)) == 0.0
    assert behave_shard._estimate(str(live)) > 0.0


def test_unmeasured_feature_is_not_weighed_as_free(tmp_path):
    """A feature absent from the table falls back to an estimate, not to zero.

    Otherwise adding a heavy feature and forgetting the table would pile it onto
    whichever shard happened to be lightest, for free, forever.
    """
    feature = tmp_path / "new.feature"
    feature.write_text("Feature: brand new\n  Scenario: one\n  Scenario: two\n", encoding="utf-8")

    weight = behave_shard._weight(str(feature), {}, "features/new.feature")

    assert weight > 0.0


def test_measurements_win_over_the_estimate(tmp_path):
    """The table is the authority where it has an entry."""
    feature = tmp_path / "measured.feature"
    feature.write_text("Feature: cheap to count, dear to run\n  Scenario: one\n", encoding="utf-8")

    weight = behave_shard._weight(str(feature), {"features/measured.feature": 900.0}, "features/measured.feature")

    assert weight == 900.0


def test_split_is_deterministic():
    """CI computes the split once per job; every job must compute the same one."""
    first, first_loads = behave_shard.shard_loads(CI_SHARDS)
    second, second_loads = behave_shard.shard_loads(CI_SHARDS)

    assert first == second
    assert first_loads == second_loads
