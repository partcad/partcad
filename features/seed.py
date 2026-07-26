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
scenario. Copying ~3.5 GB costs ~2.2s, against the minutes the cold
build costs, and the copy is deleted when the scenario ends so at most
`--parallel-processes` of them exist at a time.

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
BASE_DIR = os.environ.get("PARTCAD_BEHAVE_DIR") or os.path.join(os.path.expanduser("~"), ".partcad-behave")

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

# The sandbox the script parts run in.
_SANDBOX_DIR = os.path.join(SEED_STATE_DIR, "sandbox")

# Written only once the sandbox has been built successfully. The directory's mere
# existence is not the test: conda creates it and populates it as it goes, so an
# attempt that failed or timed out partway leaves a directory that looks built
# and is not, and skipping the rebuild would hand every scenario a broken
# sandbox. Outside SEED_STATE_DIR for the same reason as _SEED_MARKER - a
# restored cache must not be able to claim a sandbox it does not carry.
_SANDBOX_MARKER = os.path.join(SEED_ROOT, ".sandbox-built")

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
# index is the long pole, so the budget is generous; an export that has not
# finished in five minutes is stuck, not slow. The sandbox gets its own budget
# because it is solving a conda environment, not exporting geometry.
_LIST_TIMEOUT = 1800
_SANDBOX_TIMEOUT = 1800
_EXPORT_TIMEOUT = 300

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


def _build(env: dict) -> None:
    """Populate `SEED_STATE_DIR`. Raises if the parts that must work do not."""
    os.makedirs(_SEED_PROJECT_DIR, exist_ok=True)
    os.makedirs(SEED_STATE_DIR, exist_ok=True)
    output_dir = os.path.join(SEED_ROOT, "output")
    os.makedirs(output_dir, exist_ok=True)

    build_env = dict(env)
    build_env["PC_INTERNAL_STATE_DIR"] = SEED_STATE_DIR

    # `pc init` writes a package whose only dependency is `//pub`, so the
    # recursive list below walks the public index and nothing else. It refuses to
    # overwrite, so a resumed build has to skip it rather than treat the refusal
    # as a failure.
    if not os.path.exists(os.path.join(_SEED_PROJECT_DIR, "partcad.yaml")):
        result = _run(_pc_command("init"), _SEED_PROJECT_DIR, build_env, _EXPORT_TIMEOUT)
        if result.returncode != 0:
            raise RuntimeError(f"seed: 'pc init' failed ({result.returncode}):\n{result.stderr}")

    # Resolving every package in the index is what fills the git cache, and it
    # is the single most valuable thing the seed does: it is the work that was
    # previously repeated by every scenario that touched a `//pub` object.
    result = _run(_pc_command("list", "all", "-r"), _SEED_PROJECT_DIR, build_env, _LIST_TIMEOUT)
    if result.returncode != 0:
        raise RuntimeError(f"seed: 'pc list all -r' failed ({result.returncode}):\n{result.stderr}")

    # The sandbox used to appear as a side effect of the first script part
    # exported. It gets its own step now, because the loop below skips exports a
    # restored cache already covers - and on a full cache hit it would skip every
    # one of them, leaving no script part to trigger the build.
    if not (os.path.exists(_SANDBOX_MARKER) and os.path.isdir(_SANDBOX_DIR)):
        # Whatever a previous attempt left is not repairable by conda, and half
        # an environment is worse than none, so it goes before trying again.
        shutil.rmtree(_SANDBOX_DIR, ignore_errors=True)
        args = ["export", "-t", "stl", "-O", output_dir, _SANDBOX_TRIGGER]
        try:
            result = _run(_pc_command(*args), _SEED_PROJECT_DIR, build_env, _SANDBOX_TIMEOUT)
        except subprocess.TimeoutExpired as timeout:
            raise RuntimeError(f"seed: building the sandbox timed out after {_SANDBOX_TIMEOUT}s") from timeout
        if result.returncode != 0:
            raise RuntimeError(f"seed: building the sandbox failed ({result.returncode}):\n{result.stderr}")
        with open(_SANDBOX_MARKER, "w", encoding="utf-8") as marker:
            marker.write("ok\n")

    # Exporting fills the object cache. Individual combinations are allowed to
    # fail: not every type can be expressed in every format, and a type that
    # cannot be exported today should leave the suite slower, not broken.
    done = _load_manifest()
    failures = []
    skipped = 0
    for kind, objects in (("part", PART_OBJECTS), ("assembly", ASSEMBLY_OBJECTS)):
        for type_name, object_path in objects:
            for export_format in EXPORT_FORMATS:
                entry = f"{kind}|{type_name}|{export_format}"
                if entry in done:
                    skipped += 1
                    continue
                args = ["export", "-t", export_format, "-O", output_dir]
                if kind == "assembly":
                    args.append("-a")
                args.append(object_path)
                try:
                    result = _run(_pc_command(*args), _SEED_PROJECT_DIR, build_env, _EXPORT_TIMEOUT)
                    rc = result.returncode
                except subprocess.TimeoutExpired:
                    rc = "timeout"
                if rc == 0:
                    # Recorded as they succeed rather than in one write at the
                    # end, so an interrupted build still shortens the next one.
                    done.add(entry)
                    _save_manifest(done)
                else:
                    failures.append(f"{kind} {type_name} -> {export_format} ({rc})")

    if skipped:
        logger.info("seed: %d exports already covered by the restored object cache", skipped)

    if failures:
        logger.info(
            "seed: %d of %d exports did not succeed; those combinations stay cold: %s",
            len(failures),
            (len(PART_OBJECTS) + len(ASSEMBLY_OBJECTS)) * len(EXPORT_FORMATS),
            ", ".join(failures),
        )


def ensure_seed(env: dict) -> str:
    """Return the seeded state directory, building it if it is not there yet.

    Safe to call concurrently: behavex starts one behave per worker and each
    runs `before_all`, so the first caller builds while the others wait on the
    lock and then observe the marker.
    """
    os.makedirs(os.path.dirname(_SEED_LOCK) or ".", exist_ok=True)

    with FileLock(_SEED_LOCK):
        if os.path.exists(_SEED_MARKER):
            return SEED_STATE_DIR

        logger.info("seed: building the shared PartCAD state directory in %s", SEED_ROOT)

        # Whatever is already here is built on rather than discarded, because in
        # CI it is a restored cache and discarding it would defeat the point.
        # Every step in `_build` is individually resumable: PartCAD's own guard
        # file makes a half-finished clone re-clone, the sandbox is rebuilt
        # unless its directory is there, and the manifest records exports one at
        # a time. Delete BASE_DIR to force a genuinely clean rebuild.
        _build(env)

        with open(_SEED_MARKER, "w", encoding="utf-8") as marker:
            marker.write("ok\n")

        logger.info("seed: ready")
        return SEED_STATE_DIR


def provision(destination: str) -> str:
    """Copy the seed to `destination` and return it, for one scenario's use."""
    # shutil.copytree walks the ~27k files in Python; `cp -a` does the same work
    # in one process and measurably faster, which is worth having on the path
    # that runs once per scenario. Windows has no `cp`, so it falls back.
    if platform.system() == "Windows":
        shutil.copytree(SEED_STATE_DIR, destination, symlinks=True)
    else:
        os.makedirs(os.path.dirname(destination), exist_ok=True)
        subprocess.run(["cp", "-a", SEED_STATE_DIR, destination], check=True)
    return destination


def release(destination: str) -> None:
    """Delete a scenario's copy. Never fails the scenario it belongs to."""
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

    print(ensure(subprocess_env()))
