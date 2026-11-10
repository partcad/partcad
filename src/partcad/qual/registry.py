#
# PartCAD, 2025
#
# Author: Roman Kuzmenko
# Created: 2025-01-03
#
# Licensed under Apache License, Version 2.0.
#
"""Which qualifications there are, and which of them are asked of an object.

The built-in checks are one list, built once and shared by every caller, in
the order they run -- the cheapest questions first, and the ones every other
presumes before them. Each is of a subtype ('Qualification.SUBTYPE'), which
is how a run of one subtype selects them ('select()').

A plugin's check is not in that list: it is declared by the object it is asked
of, under 'qual: <subtype>:', and made for it ('declared()'), so that a run over
a package asks each object exactly what it declares beside what every object is
asked.
"""

import os
import typing

from . import config as qual_config
from .basic.cad import CadTest
from .basic.cam import CamTest
from .basic.cfd import CfdTest
from .basic.cmf import CmfTest
from .basic.connect import ConnectTest
from .basic.connectivity import ConnectivityTest
from .basic.degenerate import DegenerateTest
from .basic.dynamic import DynamicTest
from .basic.fea import FeaTest
from .basic.manufacturability import ManufacturabilityTest
from .basic.manufacturability_additive_solid import ManufacturabilityAdditiveSolidTest
from .basic.manufacturability_cut import ManufacturabilityCutTest
from .basic.manufacturability_drill import ManufacturabilityDrillTest
from .basic.manufacturability_forming import ManufacturabilityFormingTest
from .basic.manufacturability_laser import ManufacturabilityLaserTest
from .basic.manufacturability_sheet_metal import ManufacturabilitySheetMetalTest
from .basic.manufacturability_subtractive import ManufacturabilitySubtractiveTest
from .basic.requirements import RequirementsTest
from .basic.shell import ShellTest
from .basic.solidity import SolidityTest
from .basic.thermal import ThermalTest
from .basic.validity import ValidityTest
from .qualification import Qualification
from .sim import SimTest
from .topology.defects import DefectsTest
from .topology.interference import InterferenceTest
from .topology.tolerance import ToleranceEdgesTest, ToleranceSurfacesTest

_global_tests: list[Qualification] = []


def builtin(concurrency_cap: typing.Optional[int] = None) -> list[Qualification]:
    """Every built-in check, built once and shared by every caller.

    `concurrency_cap` is a cap on the tests as a whole rather than on any one of
    them, which is why it is set on the base class here rather than passed down.
    """
    if concurrency_cap is None:
        concurrency_cap = max(os.cpu_count(), 8)
    Qualification.MAX_CONCURRENT_TESTS = concurrency_cap
    if len(_global_tests) == 0:
        _global_tests.extend(
            [
                CadTest(),
                ManufacturabilityTest(),
                ManufacturabilityAdditiveSolidTest(),
                ManufacturabilitySubtractiveTest(),
                ManufacturabilityFormingTest(),
                ManufacturabilitySheetMetalTest(),
                ManufacturabilityLaserTest(),
                ManufacturabilityDrillTest(),
                ManufacturabilityCutTest(),
                ConnectTest(),
                ConnectivityTest(),
                # What the object was required to be: its ports, its interfaces
                # and its physical properties, against what 'requirements:'
                # says. A read of the declarations, plus what the solid
                # weighs where a physical property is required.
                RequirementsTest(),
                # Whether what is to be made has its colour, material and finish
                # specified: a read of the summary the payload's CMF section was
                # recorded with, so it costs nothing beyond the build the 'cad'
                # check already made (docs/design/cmf.md, section 8).
                CmfTest(),
                DegenerateTest(),
                # Costs no sandbox at all: the verdict is read off the envelope
                # the core already holds (see partcad.brep_inspect), so it goes
                # with the nearly-free checks rather than the measured ones.
                # Before solidity, which has nothing to say about a shape with no
                # solid in it - this is what says why there is none.
                ShellTest(),
                # Before interference, deliberately: a part that is inside out
                # makes every boolean against it meaningless, so knowing which
                # parts those are is what makes the interference result mean
                # anything.
                SolidityTest(),
                # Reports rather than fails: the parts it has most to say about
                # are ones nothing is functionally wrong with.
                ValidityTest(),
                # Where the two above have something to say, which pieces of the
                # part are the reason: its free edges, its slivers, and the faces
                # and edges OCCT rejects. A sandbox run per part, after the
                # whole-part checks that cost next to nothing.
                DefectsTest(),
                # Realizes the assembly and intersects the pairs whose boxes
                # meet, so it is the most expensive of the geometry checks and
                # goes after the ones that are nearly free.
                InterferenceTest(),
                # Whether every face and every edge of a part that is to be
                # made says how precisely: covered by the part's general
                # tolerance, or by a tolerance of its own in the file the part
                # is read from. Topology checks, because what is missing is a
                # place on the part, and it is shown there. A sandbox of their
                # own, after the nearly free checks; nothing for a part nobody
                # makes.
                ToleranceSurfacesTest(),
                ToleranceEdgesTest(),
                # Only ever run for an object that declares the matching
                # section; see 'qual/basic/cae.py' and 'qual/basic/cam.py'. A package with
                # no 'cam:' and no analysis section in it pays nothing for
                # these being here.
                #
                # 'cam' is the route -- can this object's post-processor produce
                # the program a machine cuts it with -- and emphatically not the
                # 'manufacturability' checks at the top of this list, which ask
                # whether it can be made or bought at all. That one answered to
                # the name 'cam' until 'pc cam' existed.
                CamTest(),
                FeaTest(),
                DynamicTest(),
                ThermalTest(),
                CfdTest(),
                # The same gate again, on 'qual: sim:', for a part or an
                # assembly: an object that declares none pays nothing. Last,
                # because a simulation builds the object and a scene around it
                # and starts a simulator, and is the most expensive question
                # here; and because what it asks -- does this do what it says
                # once the world is switched on -- presumes everything above.
                SimTest(),
            ]
        )
    return _global_tests


def select(quals: list, subtypes=None, prefix: typing.Optional[str] = None) -> list:
    """The ones of 'quals' of the subtypes 'subtypes' names (all for none), whose names start with 'prefix'."""
    chosen = qual_config.subtypes_of(subtypes)
    return [qual for qual in quals if qual.SUBTYPE in chosen and (not prefix or qual.name.startswith(prefix))]


def builtin_names(subtype: str) -> list:
    """The names of the built-in checks of 'subtype', which an object's 'qual:' may tune but not take."""
    return [qual.name for qual in builtin(Qualification.MAX_CONCURRENT_TESTS) if qual.SUBTYPE == subtype]


def declared(shape, subtypes=None, prefix: typing.Optional[str] = None) -> list:
    """The checks plugins supply that 'shape' declares, of the subtypes 'subtypes' names.

    One 'PluginQualification' per declaration, made afresh for the object it
    belongs to. A simulation is not one of them: the built-in 'sim' check runs
    every simulation an object declares.
    """
    from .plugin import PluginQualification

    result = []
    for subtype in qual_config.subtypes_of(subtypes):
        if subtype not in qual_config.PLUGIN_SUBTYPES:
            continue
        for declaration in qual_config.declared(shape, subtype, builtin_names(subtype)):
            if prefix and not declaration.name.startswith(prefix):
                continue
            result.append(PluginQualification(declaration))
    return result


def for_shape(quals: list, shape, subtypes=None, prefix: typing.Optional[str] = None) -> list:
    """What is asked of 'shape': 'quals' (already selected), then what it declares itself."""
    from ..shape import Shape

    if not isinstance(shape, Shape):
        return list(quals)
    return list(quals) + declared(shape, subtypes, prefix)
