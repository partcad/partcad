import os
import socket

# Imported for the side effect of its module body: it snapshots the PYTHON*
# variables this run was started with, and behave loads this file before any
# step definition -- which is the last moment at which that snapshot is still
# what the harness was given. See the module.
import features.pristine_env  # noqa: F401

from allure_behave.hooks import allure_report


from behave.runner import Context


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


# Scenarios tagged with this clone over SSH, which GitHub refuses without a key
# even for a public repository. They are SKIPPED (not failed) where the run has
# said it has no key -- ``PARTCAD_TEST_NO_SSH_KEY`` set to anything non-empty --
# and run everywhere else.
#
# CI sets it from what ".github/actions/preflight" found: a pull request whose
# branch lives in a fork is given no secrets, so ``SSH_PRIVATE_KEY_RO`` is not
# there to load, and these scenarios used to fail every such pull request on
# that and nothing else. The same pull request runs them in the merge queue,
# which has the key.
#
# Declared rather than probed, on purpose: a machine that has not said it lacks
# a key is taken to have one, so a key that should be there and is broken still
# fails the scenario instead of quietly skipping it.
SSH_KEY_TAG = "requires-ssh-key"


def before_scenario(context: Context, scenario) -> None:
    if NETWORK_TAG in scenario.effective_tags and not _network_available():
        scenario.skip("network not available: skipping @%s scenario" % NETWORK_TAG)
    elif SSH_KEY_TAG in scenario.effective_tags and os.environ.get("PARTCAD_TEST_NO_SSH_KEY"):
        scenario.skip("this run has no SSH key (PARTCAD_TEST_NO_SSH_KEY): skipping @%s scenario" % SSH_KEY_TAG)
    # First, so that it runs last: after the cleanups the steps register. See
    # 'features/daemons.py'.
    from features.daemons import watch_scenario_directories

    watch_scenario_directories(context)


def after_scenario(context: Context, scenario) -> None:
    # Before the scenario's cleanups, which is when behave runs this: they
    # remove the workspace and the $HOME the daemon is serving from, and on
    # Windows cannot while it runs. See 'features/daemons.py'.
    from features.daemons import stop_scenario_daemon

    stop_scenario_daemon(context)


# def before_all(context: Context) -> None:
#     import steps

#     allure_report("allure-results")
