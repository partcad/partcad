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


def before_scenario(context: Context, scenario) -> None:
    if NETWORK_TAG in scenario.effective_tags and not _network_available():
        scenario.skip("network not available: skipping @%s scenario" % NETWORK_TAG)


# def before_all(context: Context) -> None:
#     import steps

#     allure_report("allure-results")
