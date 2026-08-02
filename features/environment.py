import logging
import os
import socket
import uuid

from allure_behave.hooks import (  # noqa: F401  # used by the commented-out reporting hook below
    allure_report,
)
from behave.runner import Context

from features.seed import (
    SCENARIO_STATE_ROOT,
    ensure_seed,
    provision,
    prune_sandbox_venvs,
    release,
    sandbox_venvs,
)

# Caps on the thread pools the numeric stack creates when it is imported.
#
# `import partcad` reaches build123d, which reaches scipy, which asks its BLAS
# for one thread per core at import time. On an idle workstation that hides in
# the spare cores, but it is ~8s of CPU on every `pc` invocation against ~1.4s
# with these set, and the suite starts hundreds of them. It matters most exactly
# where there is no headroom: a 2-core CI runner, and any run under
# `--parallel-processes`, where the workers would otherwise each try to fill the
# whole machine.
THREAD_LIMIT_ENV = {
    "OMP_NUM_THREADS": "1",
    "OPENBLAS_NUM_THREADS": "1",
    "MKL_NUM_THREADS": "1",
    "NUMEXPR_NUM_THREADS": "1",
    "VECLIB_MAXIMUM_THREADS": "1",
}

# Scenarios carrying this tag assert on PartCAD's shipped telemetry behaviour -
# that it defaults to Sentry, and that `pc system set telemetry` changes it.
# Forcing a value through the environment would decide the answer before the
# command ran, so they are the one place the default is left alone.
TELEMETRY_TAG = "pc-system-telemetry"

# Scenarios carrying this tag are left entirely alone: no seed copy, and
# PC_INTERNAL_STATE_DIR unset, so PartCAD falls back to `$HOME/.partcad` and
# finds it empty because the scenario's `$HOME` is a fresh temporary directory.
# Two kinds of assertion need that. Some assert on cache-miss behaviour -
# `pc install` reports "Cloning the GIT repo:", which it does not do for a
# repository the seed already cloned. Others assert on the default location
# itself, which pointing PC_INTERNAL_STATE_DIR elsewhere would change. They pay
# the cold-start cost the rest of the suite no longer does, which is the point.
COLD_STATE_TAG = "cold-state"


# Scenarios tagged with this require live outbound network access (e.g. an
# SSH/HTTPS git clone from github.com). They are SKIPPED (not failed) when the
# environment has no connectivity -- as in a sandboxed CI runner -- and run
# normally when the network is reachable.
NETWORK_TAG = "requires-network"


def _network_available(host: str = "github.com", port: int = 443, timeout: float = 3.0) -> bool:
    """Best-effort probe that outbound network to ``host:port`` works.

    Deliberately fast and defensive: any failure (DNS error, refused
    connection, timeout) -- or the ``PARTCAD_TEST_NO_NETWORK`` override -- is
    treated as "no network" so the tagged scenario is skipped rather than
    failing where connectivity is unavailable.
    """
    # Explicit override for offline/sandboxed CI, where even the probe may hang.
    if os.environ.get("PARTCAD_TEST_NO_NETWORK"):
        return False
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


# def before_all(context: Context) -> None:
#     import steps

#     allure_report("allure-results")


def subprocess_env() -> dict:
    """The environment the suite's `pc` invocations inherit."""
    env = dict(os.environ)
    env.update(THREAD_LIMIT_ENV)
    return env


def before_all(context: Context) -> None:
    # Applied to this process rather than handed to each subprocess, so that
    # anything the suite starts inherits them, including the seed build below.
    os.environ.update(THREAD_LIMIT_ENV)

    # Building here rather than in a fixture keeps `behave` usable on its own.
    # Under behavex every worker reaches this line; `ensure_seed` locks so only
    # the first one builds. CI builds it in an earlier step, and then all of
    # them find the marker already written and return immediately.
    context.seed_state_dir = ensure_seed(subprocess_env())

    # What the shared sandbox looked like once seeding finished. Anything a
    # scenario adds to it is removed again in after_scenario; see sandbox_venvs.
    context.sandbox_baseline = sandbox_venvs() if context.seed_state_dir else set()

    # Pruning is only safe while this process is the sandbox's only user.
    # behavex runs several behave processes against the same shared sandbox and
    # tells each one its worker id, so a worker past the first must leave other
    # workers' venvs alone: "appeared since seeding" cannot distinguish one this
    # scenario made from one another worker is running out of right now.
    # Serial `behave`, which is how CI shards run, has no such reader.
    worker = str(context.config.userdata.get("worker_id", "0"))
    context.sandbox_exclusive = worker in ("", "0")
    if not context.sandbox_exclusive:
        logging.info(
            "Parallel worker %s: leaving the shared sandbox alone. Venvs built by scenarios will "
            "accumulate for this run; that is disk, where pruning them would be a race.",
            worker,
        )


def before_scenario(context: Context, scenario) -> None:
    # Skipping comes first, and returns: there is no point provisioning a state
    # directory for a scenario that is not going to run, and `release` in
    # after_scenario would then have to tidy up after a scenario that never
    # started. This and the seed setup below were separate `before_scenario`
    # definitions after a merge, where the second silently shadowed the first.
    if NETWORK_TAG in scenario.effective_tags and not _network_available():
        scenario.skip("network not available: skipping @%s scenario" % NETWORK_TAG)
        return

    if not hasattr(context, "env"):
        context.env = {}

    # Every `pc` invocation in this scenario reads and writes its own copy of
    # the seed instead of `$HOME/.partcad`. A step that sets
    # PC_INTERNAL_STATE_DIR explicitly runs after this hook and overwrites it,
    # which is what the scenarios exercising `--internal-state-dir` rely on.
    #
    # `seed_state_dir` is None when the seed could not be built - see
    # ensure_seed. Then this does nothing and the scenario runs against the cold
    # `$HOME/.partcad` in its temporary home, which is what it did before the
    # seed existed: slower, but the same scenario.
    if context.seed_state_dir and COLD_STATE_TAG not in scenario.effective_tags:
        state_dir = os.path.join(SCENARIO_STATE_ROOT, f"state-{os.getpid()}-{uuid.uuid4().hex[:8]}")
        provision(state_dir)
        context.state_dir = state_dir
        context.env["PC_INTERNAL_STATE_DIR"] = state_dir

    # Left unset for the telemetry scenarios; see TELEMETRY_TAG. Everywhere else
    # this stops each invocation from opening a connection to Sentry and
    # flushing it on exit, which the suite was doing several times per command.
    if TELEMETRY_TAG not in scenario.effective_tags:
        context.env["PC_TELEMETRY_TYPE"] = "none"


def after_scenario(context: Context, scenario) -> None:
    state_dir = getattr(context, "state_dir", None)
    if state_dir:
        release(state_dir)
        logging.debug("Removed scenario state directory: %s", state_dir)

    # Only when nothing else is using the sandbox; see before_all.
    if not getattr(context, "sandbox_exclusive", True):
        return

    # The sandbox is shared, so anything this scenario built inside it would
    # otherwise outlive it and accumulate for the whole run.
    baseline = getattr(context, "sandbox_baseline", None)
    if baseline is not None:
        prune_sandbox_venvs(baseline)
