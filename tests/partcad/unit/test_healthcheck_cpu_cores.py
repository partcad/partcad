#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The CpuCores healthcheck: a machine with fewer cores than PartCAD's minimum.

PartCAD runs four threads and four sandbox processes at the least, whatever the
machine has; on fewer cores than that it works, slowly. So it is a warning, and
the sentence is the one the sizing itself says once per process.
"""

import pytest

from partcad.healthcheck import cpu_cores
from partcad.healthcheck.tests import SEVERITY_WARNING, discover_healthchecks


@pytest.mark.parametrize("cores", [1, 2, 3])
def test_fewer_cores_than_the_minimum_are_a_finding(monkeypatch, cores):
    monkeypatch.setattr("partcad_utils.user_config.os.cpu_count", lambda: cores)

    findings = cpu_cores.CpuCoresCheck().test().findings

    assert findings == ["PartCAD needs at least 4 CPU cores for optimal performance, and found %d" % cores]


@pytest.mark.parametrize("cores", [4, 8])
def test_enough_cores_pass(monkeypatch, cores):
    monkeypatch.setattr("partcad_utils.user_config.os.cpu_count", lambda: cores)
    assert cpu_cores.CpuCoresCheck().test().findings == []


def test_it_warns_rather_than_fails():
    """Everything still works on such a machine, which is what a warning means here."""
    assert cpu_cores.CpuCoresCheck().severity == SEVERITY_WARNING


def test_it_is_run_by_pc_healthcheck():
    assert "CpuCores" in [check.name for check in discover_healthchecks()]
