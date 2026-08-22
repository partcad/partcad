#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""A pre-warmed PartCAD internal state directory shared by the whole suite.

Every scenario that runs `pc` gets a private `$HOME`, and PartCAD roots its
entire on-disk state - the git cache of imported packages and the conda sandbox
it runs script parts in - at `$HOME/.partcad`. A private `$HOME` therefore means
a cold cache, so each scenario re-cloned the `//pub` tree and rebuilt a ~2.3 GB
conda environment from scratch. One such sandbox build was observed stalling the
suite for ~35 minutes; the suite paid that cost over and over.

This module builds that state once, in `SEED_ROOT`, and hands every scenario a
copy of it. The copy is what keeps the scenarios independent: a scenario may
write to its state directory (populate the cache, re-clone at a different
revision, corrupt it on purpose) without any of it reaching the seed or the next
scenario. Copying ~3.5 GB costs ~2.2s, against the minutes the cold build costs,
and the copy is deleted when the scenario ends - so one exists at a time under
plain `behave`, and one per worker under `behavex --parallel-processes`.

Seeding is an optimization, never a precondition: if it cannot be done - a runner
that cannot reach github.com, most often - `ensure_seed` says so and returns
None, and every scenario falls back to the cold `$HOME/.partcad` it used before
this existed.

The seed is built by `ensure_seed()`, which is safe to call from every behavex
worker at once: an inter-process lock serializes them and a marker file written
last means a build that died halfway is never mistaken for a finished one.

Run `python -m features.seed` to build the seed ahead of time - CI does this so
the cost lands in its own step rather than inside the first worker to start.
"""

import json
import logging
import os
import platform
import shutil
import subprocess
import sys
import time

from filelock import FileLock

# Everything this module writes lives under here. Overridable so CI can place it
# on a volume it caches, and so a developer can point several checkouts at one
# already-built seed.
#
# Deliberately not `tempfile.gettempdir()`. behavex points the TEMP environment
# variable at its own output folder, and each worker is a separate process that
# imports this module, so a temp-derived default would give every worker a
# different location: each would rebuild the whole seed instead of sharing it,
# and each would drop multi-gigabyte scenario copies inside the very folder CI
# archives as an artifact. The home directory is identical in every worker and
# outside anything that gets uploaded.
#
# Normalised, because on Windows this arrives from CI as a POSIX-style path and
# everything derived from it is then joined with backslashes. Python does not
# care, but `cmd` does: `mklink /J D:/partcad-behave\state\...` reads the
# forward-slash segment as a switch and fails, which took out every scenario on
# every Windows shard until the paths were made consistent.
BASE_DIR = os.path.normpath(
    os.environ.get("PARTCAD_BEHAVE_DIR") or os.path.join(os.path.expanduser("~"), ".partcad-behave")
)

# The seed, built once.
SEED_ROOT = os.path.join(BASE_DIR, "seed")

# The state directory itself - this is what gets copied per scenario.
SEED_STATE_DIR = os.path.join(SEED_ROOT, "state")

# Where the per-scenario copies go. Kept together so that an interrupted run
# leaves one identifiable tree to delete rather than scattering copies about.
SCENARIO_STATE_ROOT = os.path.join(BASE_DIR, "state")

# The throwaway package the seeding commands run in. It is not copied; only the
# state directory the commands populate as a side effect is.
_SEED_PROJECT_DIR = os.path.join(SEED_ROOT, "project")

# Written last, once the build has fully succeeded. Its absence means "rebuild".
#
# Deliberately outside SEED_STATE_DIR, and so deliberately outside what CI
# caches. A restored cache brings back the expensive-to-produce parts but not the
# conda sandbox, which is too large to be worth a cache slot and cheap to
# rebuild; if this marker came back with them, the build would be skipped, the
# sandbox would never be built, and every scenario needing it would build one
# inside its own throwaway copy of the state directory.
_SEED_MARKER = os.path.join(SEED_ROOT, ".seeded")

# Records the (kind, type, format) exports already done, so a build that finds a
# restored object cache does not spend ~7.5 minutes re-exporting what is in it.
# Inside the state directory, and so cached alongside the cache it describes -
# the two are only meaningful together.
_EXPORTS_MANIFEST = os.path.join(SEED_STATE_DIR, ".seed-exports.json")

# The parts of the state directory each scenario gets a private copy of: the
# caches it may write to and would otherwise have to refill. Everything else in
# there is either shared (the sandbox, see provision) or scenario-irrelevant.
_COPIED_SUBDIRS = ("cache", "git", "external")

# The sandbox the script parts run in.
_SANDBOX_DIR = os.path.join(SEED_STATE_DIR, "sandbox")

# Written only once the sandbox has been built successfully. The directory's mere
# existence is not the test: conda creates it and populates it as it goes, so an
# attempt that failed or timed out partway leaves a directory that looks built
# and is not, and skipping the rebuild would hand every scenario a broken
# sandbox. Outside SEED_STATE_DIR for the same reason as _SEED_MARKER - a
# restored cache must not be able to claim a sandbox it does not carry.
_SANDBOX_MARKER = os.path.join(SEED_ROOT, ".sandbox-built")

# Records a failed attempt so that the other behavex workers, each of which
# calls ensure_seed, do not queue up to repeat it. Expires, so that a later run
# is never held back by an old failure - the point is to avoid N workers paying
# the same doomed budget in one run, not to remember it.
_SEED_FAILED_MARKER = os.path.join(SEED_ROOT, ".seed-failed")
_FAILURE_TTL = int(os.environ.get("PARTCAD_BEHAVE_FAILURE_TTL", "900"))

# Kept beside SEED_ROOT rather than inside it, so that discarding a failed seed
# never deletes the lock the discarding process is holding.
_SEED_LOCK = SEED_ROOT + ".lock"

# Every format `pc export` accepts. The seed exports each object below to each
# of them so the first scenario to ask for any combination finds it warm.
EXPORT_FORMATS = (
    "step",
    "brep",
    "stl",
    "3mf",
    "threejs",
    "obj",
    "gltf",
    "iges",
)

# One representative object per part type published in `//pub`, paired with the
# type it exercises. Hardcoded rather than discovered because discovery would
# mean resolving all ~12k objects in the index on every run, and because the
# point is to pin what the seed covers so a change to it is visible in review.
#
# `//pub` tracks a released PartCAD, so it lags this checkout: types the repo has
# under `examples/` but the index has not published yet (`sdf`, `compound`) have
# no entry here and stay cold. The `ai-*` types are published but deliberately
# left out - generating them calls a model provider, which needs credentials and
# is what the suite-wide `~@ai` tag already excludes.
PART_OBJECTS = (
    ("step", "//pub/examples/partcad/produce_part_step:bolt"),
    ("stl", "//pub/examples/partcad/produce_part_stl:cube"),
    ("3mf", "//pub/examples/partcad/produce_part_3mf:cube"),
    ("brep", "//pub/examples/partcad/produce_part_brep:box"),
    ("obj", "//pub/examples/partcad/produce_part_obj:cube"),
    ("build123d", "//pub/examples/partcad/produce_part_build123d_primitive:cube"),
    ("cadquery", "//pub/examples/partcad/produce_part_cadquery_primitive:cube"),
    ("scad", "//pub/examples/partcad/produce_part_openscad:cube"),
    ("extrude", "//pub/examples/partcad/produce_part_extrude:cylinder"),
    ("sweep", "//pub/examples/partcad/produce_part_sweep:pipe"),
    ("kicad", "//pub/examples/partcad/produce_part_kicad:Arduino_Nano"),
    ("alias", "//pub/examples/partcad/produce_part_step:screw"),
    ("enrich", "//pub/examples/partcad/feature_convert:cube_enrich"),
)

# The same, for the assembly types `//pub` publishes.
ASSEMBLY_OBJECTS = (
    ("assy", "//pub/examples/partcad/produce_assembly_assy:primitive"),
    ("alias", "//pub/examples/partcad/produce_assembly_assy:partcad_logo"),
)

# The object exported purely to force the conda sandbox into existence. Any
# script-backed type would do; cadquery is the cheapest one `//pub` publishes.
_SANDBOX_TRIGGER = "//pub/examples/partcad/produce_part_cadquery_primitive:cube"

# No single seeding command should be able to wedge a CI run. Cloning the whole
# index is the long pole; an export that has not finished in five minutes is
# stuck, not slow. The sandbox gets its own allowance because it is solving a
# conda environment, not exporting geometry.
_LIST_TIMEOUT = 900
_SANDBOX_TIMEOUT = 900
_EXPORT_TIMEOUT = 300

# Wall-clock budget for the whole of seeding, retries included.
#
# Per-command timeouts alone do not bound this: three attempts at two 900s steps
# is 45 minutes before the exports even start, which on a runner with flaky
# connectivity would eat a 60 minute job by itself. Every phase is therefore
# given whatever is left of this and no more, and once it is gone seeding stops
# and the suite runs unseeded rather than the job being killed.
_SEED_BUDGET = int(os.environ.get("PARTCAD_BEHAVE_SEED_BUDGET", "1500"))

# Attempts per seeding step, and the base backoff between them (multiplied by
# the attempt number). Cloning the index and solving a conda environment both
# reach the network, and hosted runners lose connections to github.com often
# enough that one attempt is not a fair test of whether seeding is possible.
_ATTEMPTS = 3
_RETRY_DELAY = 10

# Wall-clock budget for the export phase as a whole. It exists because a CI job
# has a deadline the seed shares with the suite it is meant to speed up: on a
# Windows runner the unbounded phase took 32 of the job's 60 minutes and the
# suite was killed before finishing. Exports are resumable through the manifest,
# so a budget defers work rather than dropping it. Overridable for a machine that
# would rather pay once and be done.
_EXPORT_BUDGET = int(os.environ.get("PARTCAD_BEHAVE_EXPORT_BUDGET", "600"))


class SeedError(Exception):
    """A seeding step could not be completed, after retrying."""


logger = logging.getLogger(__name__)


def _pc_command(*args: str) -> list:
    """The argv that runs this checkout's `pc` under the running interpreter.

    Going through `sys.executable -m` rather than a `pc` on PATH keeps the seed
    on the same interpreter behave itself is using, which matters in CI where
    the environment is a conda env activated for the job. Unlike the test steps,
    which wrap the CLI in `coverage run` on the one cell that reports coverage
    (see features/steps/run.py), the seed never does: it is fixture setup, and
    attributing it would credit lines no scenario actually exercised.
    """
    return [sys.executable, "-m", "partcad_cli.click.command", "--no-ansi", *args]


def _run(argv: list, cwd: str, env: dict, timeout: int) -> subprocess.CompletedProcess:
    logger.debug("seed: running %s", " ".join(argv[3:]))
    return subprocess.run(
        argv,
        cwd=cwd,
        env=env,
        timeout=timeout,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )


def _load_manifest() -> set:
    """The exports a previous build - possibly a cached one - already did."""
    try:
        with open(_EXPORTS_MANIFEST, encoding="utf-8") as manifest:
            return set(json.load(manifest))
    except (OSError, ValueError):
        # Missing is the normal first-run case. Unreadable or malformed means a
        # build died mid-write, and redoing every export is the safe answer.
        return set()


def _save_manifest(done: set) -> None:
    with open(_EXPORTS_MANIFEST, "w", encoding="utf-8") as manifest:
        json.dump(sorted(done), manifest)


def _budget_left(deadline: float, label: str) -> float:
    """Seconds left of the overall seeding budget, or raise if it is spent."""
    left = deadline - time.monotonic()
    if left <= 0:
        raise SeedError(f"the {_SEED_BUDGET}s seeding budget was spent before {label} could run")
    return left


def _run_step(label: str, argv: list, cwd: str, env: dict, allowance: int, deadline: float) -> None:
    """Run one seeding command, retrying until it works or the budget is gone.

    The steps that matter here reach the network - cloning the whole public
    index, and solving a conda environment - and hosted runners drop connections
    to github.com often enough that a single attempt is not a fair test of
    whether seeding is possible.

    Every attempt is clamped to whatever is left of the overall deadline, not
    just to this step's own allowance. Clamping only to the allowance would let
    three attempts at a 900s step run for 45 minutes, which is the whole point of
    having a budget.

    Each step is timed and logged: seeding runs on machines an order of magnitude
    apart in speed, and without per-phase numbers a slow job says only that the
    whole thing took half an hour.
    """
    started = time.monotonic()
    detail = "no attempt made"
    for attempt in range(1, _ATTEMPTS + 1):
        timeout = min(allowance, _budget_left(deadline, label))
        try:
            result = _run(argv, cwd, env, timeout)
            if result.returncode == 0:
                logger.info("seed: %s took %.0fs", label, time.monotonic() - started)
                return
            stderr = (result.stderr or "").strip()
            detail = stderr.splitlines()[-1] if stderr else f"exit status {result.returncode}"
        except subprocess.TimeoutExpired:
            detail = f"timed out after {timeout:.0f}s"
        if attempt < _ATTEMPTS:
            delay = _RETRY_DELAY * attempt
            # Sleeping past the deadline only to be refused by the clamp above
            # wastes time the suite could be using.
            if time.monotonic() + delay >= deadline:
                raise SeedError(f"{label} failed ({detail}) and the seeding budget is spent")
            logger.warning("seed: %s failed (%s); retrying in %ds", label, detail, delay)
            time.sleep(delay)
    raise SeedError(f"{label} failed after {_ATTEMPTS} attempts: {detail}")


def _build(env: dict) -> None:
    """Populate `SEED_STATE_DIR`. Raises SeedError if a required step will not run."""
    os.makedirs(_SEED_PROJECT_DIR, exist_ok=True)
    os.makedirs(SEED_STATE_DIR, exist_ok=True)
    output_dir = os.path.join(SEED_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)

    build_env = dict(env)
    build_env["PC_INTERNAL_STATE_DIR"] = SEED_STATE_DIR

    # Everything below shares this deadline, so that seeding costs a job a
    # bounded amount no matter how badly the network behaves.
    deadline = time.monotonic() + _SEED_BUDGET

    # `pc init` writes a package whose only dependency is `//pub`, so the
    # recursive list below walks the public index and nothing else. It refuses to
    # overwrite, so a resumed build has to skip it rather than treat the refusal
    # as a failure.
    if not os.path.exists(os.path.join(_SEED_PROJECT_DIR, "partcad.yaml")):
        _run_step(
            "'pc init'",
            _pc_command("init"),
            _SEED_PROJECT_DIR,
            build_env,
            _EXPORT_TIMEOUT,
            deadline,
        )

    # Resolving every package in the index is what fills the git cache, and it
    # is the single most valuable thing the seed does: it is the work that was
    # previously repeated by every scenario that touched a `//pub` object.
    _run_step(
        "'pc list all -r'",
        _pc_command("list", "all", "-r"),
        _SEED_PROJECT_DIR,
        build_env,
        _LIST_TIMEOUT,
        deadline,
    )

    # The sandbox used to appear as a side effect of the first script part
    # exported. It gets its own step now, because the loop below skips exports a
    # restored cache already covers - and on a full cache hit it would skip every
    # one of them, leaving no script part to trigger the build.
    if not (os.path.exists(_SANDBOX_MARKER) and os.path.isdir(_SANDBOX_DIR)):
        # Whatever a previous attempt left is not repairable by conda, and half
        # an environment is worse than none, so it goes before trying again.
        shutil.rmtree(_SANDBOX_DIR, ignore_errors=True)
        _run_step(
            "building the sandbox",
            _pc_command("export", "-t", "stl", "-O", output_dir, _SANDBOX_TRIGGER),
            _SEED_PROJECT_DIR,
            build_env,
            _SANDBOX_TIMEOUT,
            deadline,
        )
        with open(_SANDBOX_MARKER, "w", encoding="utf-8") as marker:
            marker.write("ok\n")

    # Exporting fills the object cache. Individual combinations are allowed to
    # fail: not every type can be expressed in every format, and a type that
    # cannot be exported today should leave the suite slower, not broken.
    #
    # The phase is also time-boxed, because it is the one part of the seed whose
    # cost scales with how much it covers, and it is the least valuable per
    # second: the clone and the sandbox above are what stop every scenario
    # repeating minutes of work, while these only pre-warm objects some scenarios
    # then export again. Unbounded, it took 32 of a Windows job's 60 allowed
    # minutes and left too little for the suite, so the job was killed.
    #
    # Stopping early is not giving up. Each success is recorded in the manifest
    # as it happens, and CI caches the manifest with the objects it describes, so
    # the next run resumes where this one stopped and the coverage converges over
    # a few runs instead of being paid all at once.
    done = _load_manifest()
    failures = []
    skipped = 0
    exported = 0
    remaining = 0
    # Whichever runs out first: the phase's own budget, or what is left of the
    # overall one after cloning and building the sandbox.
    export_deadline = min(time.monotonic() + _EXPORT_BUDGET, deadline)
    for kind, objects in (("part", PART_OBJECTS), ("assembly", ASSEMBLY_OBJECTS)):
        for type_name, object_path in objects:
            for export_format in EXPORT_FORMATS:
                entry = f"{kind}|{type_name}|{export_format}"
                if entry in done:
                    skipped += 1
                    continue
                if time.monotonic() >= export_deadline:
                    remaining += 1
                    continue
                args = ["export", "-t", export_format, "-O", output_dir]
                if kind == "assembly":
                    args.append("-a")
                args.append(object_path)
                try:
                    export_timeout = min(_EXPORT_TIMEOUT, max(1, export_deadline - time.monotonic()))
                    result = _run(_pc_command(*args), _SEED_PROJECT_DIR, build_env, export_timeout)
                    rc = result.returncode
                except subprocess.TimeoutExpired:
                    rc = "timeout"
                if rc == 0:
                    # Recorded as they succeed rather than in one write at the
                    # end, so an interrupted build still shortens the next one.
                    done.add(entry)
                    _save_manifest(done)
                    exported += 1
                else:
                    failures.append(f"{kind} {type_name} -> {export_format} ({rc})")

    total = (len(PART_OBJECTS) + len(ASSEMBLY_OBJECTS)) * len(EXPORT_FORMATS)
    logger.info(
        "seed: exports - %d done now, %d already cached, %d deferred, %d failed (of %d)",
        exported,
        skipped,
        remaining,
        len(failures),
        total,
    )

    if remaining:
        logger.info(
            "seed: the %ds export budget ran out with %d left; they stay cold until a later run picks "
            "them up from the manifest",
            _EXPORT_BUDGET,
            remaining,
        )

    if failures:
        logger.info("seed: these combinations stay cold: %s", ", ".join(failures))


def _record_failure(reason: str) -> None:
    """Note that seeding just failed, so sibling workers do not each retry it."""
    try:
        os.makedirs(SEED_ROOT, exist_ok=True)
        with open(_SEED_FAILED_MARKER, "w", encoding="utf-8") as marker:
            json.dump({"at": time.time(), "reason": reason}, marker)
    except OSError:
        # Only an optimization; failing to record it costs a retry, not
        # correctness.
        pass


def _recent_failure():
    """(age, reason) if seeding failed recently enough to trust, else None."""
    try:
        with open(_SEED_FAILED_MARKER, encoding="utf-8") as marker:
            record = json.load(marker)
        age = time.time() - float(record["at"])
    except (OSError, ValueError, KeyError, TypeError):
        return None
    if age < 0 or age > _FAILURE_TTL:
        return None
    return age, record.get("reason", "unknown")


def ensure_seed(env: dict):
    """Return the seeded state directory, or None if it could not be built.

    None is a supported outcome, not an error: the seed is an optimization, so a
    runner that cannot reach github.com should still run the suite - each
    scenario falling back to the cold `$HOME/.partcad` it used before this
    existed. Correct, and much slower. Raising instead would turn one dropped
    connection into a failure of every sharded behave job, which is exactly what
    it did the first time this ran on the macOS runners.

    Safe to call concurrently: behavex starts one behave per worker and each
    runs `before_all`, so the first caller builds while the others wait on the
    lock and then observe the marker.
    """
    os.makedirs(os.path.dirname(_SEED_LOCK) or ".", exist_ok=True)

    with FileLock(_SEED_LOCK):
        if os.path.exists(_SEED_MARKER):
            return SEED_STATE_DIR

        # A failure just recorded is taken at face value rather than retried.
        # behavex starts one behave per worker and each calls this, so without
        # it a seed that cannot be built is attempted once per worker, each
        # spending the full budget on the same doomed clone. The record expires
        # so that a later run - a new job, or the developer trying again after
        # fixing their network - is never held back by an old failure.
        recorded = _recent_failure()
        if recorded:
            logger.warning("seed: not retrying, seeding failed %.0fs ago in this run: %s", recorded[0], recorded[1])
            return None

        logger.info("seed: building the shared PartCAD state directory in %s", SEED_ROOT)

        # Whatever is already here is built on rather than discarded, because in
        # CI it is a restored cache and discarding it would defeat the point.
        # Every step in `_build` is individually resumable: PartCAD's own guard
        # file makes a half-finished clone re-clone, the sandbox is rebuilt
        # unless its success marker is there, and the manifest records exports
        # one at a time. Delete BASE_DIR to force a genuinely clean rebuild.
        try:
            _build(env)
        except SeedError as error:
            _record_failure(str(error))
            logger.warning("seed: %s", error)
            logger.warning(
                "seed: continuing WITHOUT a shared state directory - every scenario will start from a cold "
                "cache, which is correct but much slower. This is usually a runner that cannot reach "
                "github.com; re-run the job."
            )
            return None

        with open(_SEED_MARKER, "w", encoding="utf-8") as marker:
            marker.write("ok\n")

        logger.info("seed: ready")
        return SEED_STATE_DIR


def _copy_dir(source: str, destination: str) -> None:
    """Copy one directory. `cp -a` beats shutil.copytree, which walks in Python."""
    if platform.system() == "Windows":
        shutil.copytree(source, destination, symlinks=True)
    else:
        subprocess.run(["cp", "-a", source, destination], check=True)


def _link_dir(source: str, destination: str) -> None:
    """Point `destination` at `source` without copying it.

    A directory symlink on Windows needs either administrator rights or
    Developer Mode, neither of which a hosted runner offers, so it gets a
    junction instead - `mklink /J` is a cmd builtin and needs no privileges on
    NTFS. Everywhere else a symlink does.
    """
    if platform.system() == "Windows":
        # _winapi.CreateJunction rather than 'cmd /c mklink /J'. Going through
        # cmd means cmd re-parses the paths: a forward slash starts a switch
        # (which is how moving the seed to D: broke every Windows shard), and
        # '&', '|' or '%VAR%' in a path would be interpreted rather than used.
        # The API call takes the strings as given.
        import _winapi  # noqa: PLC0415  # Windows-only, and absent elsewhere

        _winapi.CreateJunction(os.path.normpath(source), os.path.normpath(destination))
    else:
        os.symlink(source, destination, target_is_directory=True)


def provision(destination: str) -> str:
    """Give one scenario a state directory of its own, and return it.

    Only the package and object caches are copied. The conda sandbox is shared
    through a link, because copying it is what made this unaffordable: it is
    36k of the seed's 39k files, and on a Windows runner copying the whole seed
    cost ~133s per scenario against ~2s on Linux - more than an hour per shard,
    which is why those jobs were being killed at the 60 minute cap. Copying the
    directories below is ~2.8k files and half a second.

    Sharing the sandbox is safe for the way CI runs the suite: behave is serial
    within a shard, so one scenario uses it at a time, and it is what a
    developer's own machine does anyway - PartCAD locks it across processes
    (see the FileLocks in runtime_python_conda.py). It does mean a scenario that
    corrupted the sandbox would affect later ones in the same job, and that
    concurrent workers under `behavex --parallel-processes` share it; the
    scenarios that care about a cold or private state directory are tagged
    @cold-state and get no copy at all.
    """
    os.makedirs(destination, exist_ok=True)

    # 'tar' is deliberately not here: nothing in the seed produces one today, so
    # copying it would be a no-op, and a scenario that does use a tar dependency
    # simply downloads it as it did before.
    for name in _COPIED_SUBDIRS:
        source = os.path.join(SEED_STATE_DIR, name)
        if os.path.isdir(source):
            _copy_dir(source, os.path.join(destination, name))

    # Without this the scenario would find no sandbox under its own state
    # directory and build a fresh 2.3 GB one, which is the cost this whole
    # module exists to remove.
    sandbox = os.path.join(SEED_STATE_DIR, "sandbox")
    if os.path.isdir(sandbox):
        _link_dir(sandbox, os.path.join(destination, "sandbox"))

    return destination


def sandbox_venvs() -> set:
    """The per-project virtual environments currently inside the shared sandbox.

    PartCAD builds one of these per project that runs a script part, as
    `<sandbox>/<runtime>/v-env-<hash>` (runtime_python.py). While each scenario
    copied the sandbox they died with the copy; now that it is shared they would
    accumulate for the length of the run, which is how a Windows job ran out of
    disk after 65 scenarios. Snapshotting them after seeding and removing what
    appears later restores the old lifetime without restoring the old cost.
    """
    found = set()
    sandbox = os.path.join(SEED_STATE_DIR, "sandbox")
    if not os.path.isdir(sandbox):
        return found
    try:
        for runtime in os.scandir(sandbox):
            if not runtime.is_dir():
                continue
            for entry in os.scandir(runtime.path):
                if entry.is_dir() and entry.name.startswith("v-env-"):
                    found.add(entry.path)
    except OSError:
        # Worth no more than it costs: a snapshot that cannot be taken means
        # nothing gets pruned, which is the behaviour before this existed.
        pass
    return found


def prune_sandbox_venvs(baseline: set) -> None:
    """Remove venvs the seed did not leave behind, keeping the seed's own.

    Only safe while this process is the only one using the sandbox, which is why
    the caller has to say so: the sandbox is shared, so under
    `behavex --parallel-processes` "a venv that appeared since seeding" may well
    be one another worker is running a scenario out of right now, and deleting
    it would fail that scenario for reasons impossible to reproduce. Serial runs
    - which is how CI shards behave - have no such reader.
    """
    for path in sandbox_venvs() - baseline:
        shutil.rmtree(path, ignore_errors=True)
        logger.debug("seed: pruned scenario venv %s from the shared sandbox", path)


def release(destination: str) -> None:
    """Delete a scenario's copy. Never fails the scenario it belongs to."""
    # The sandbox here is a link to the shared one, and detaching it before the
    # delete is a safety requirement rather than tidiness. shutil.rmtree does not
    # follow POSIX symlinks, but a Windows junction is a mount-point reparse
    # point that os.path.islink() reports as False and scandir can report as a
    # real directory - so an rmtree that reached one could walk through it and
    # delete the seed's sandbox, wrecking every later scenario in the job.
    #
    # os.rmdir removes a junction without touching what it points at, which is
    # why the isdir branch is safe and is the one that runs on Windows.
    sandbox = os.path.join(destination, "sandbox")
    try:
        if os.path.islink(sandbox):
            os.unlink(sandbox)
        elif os.path.isdir(sandbox):
            os.rmdir(sandbox)
    except OSError as error:
        # Leaving a scenario's directory behind costs disk. Deleting it with the
        # link still in place could cost the seed, so the leak is the better bug:
        # this is louder than a leak deserves precisely because it should not
        # happen, and the alternative is silent and unrecoverable.
        logger.warning(
            "seed: could not detach the shared sandbox at %s (%s); leaving %s in place rather than "
            "risking a delete that follows the link into the seed",
            sandbox,
            error,
            destination,
        )
        return

    shutil.rmtree(destination, ignore_errors=True)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(levelname)s:%(name)s:%(message)s")

    # Both imports are deferred to here because `features.environment` imports
    # this module: at module scope they would be a cycle. `ensure_seed` is
    # re-imported rather than called directly because `-m` runs this file as
    # `__main__`, a second module object from the `features.seed` that
    # `features.environment` holds - calling that one keeps the whole run
    # working against a single copy of this module's state.
    from features.environment import subprocess_env  # noqa: E402
    from features.seed import ensure_seed as ensure  # noqa: E402

    seeded = ensure(subprocess_env())
    # Exit 0 either way. A CI step that fails here would take the whole sharded
    # behave job with it over what is only a lost optimization; the warning
    # ensure_seed logs is what says the run will be slow.
    print(seeded if seeded else "not seeded")
