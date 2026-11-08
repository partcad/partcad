#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object declares under 'qual:', read in one place.

Everything an object says about how it is qualified lives in one section of its
declaration, one mapping per subtype:

    parts:
      bracket:
        qual:
          basic:
            cmf:                          # parameters of a built-in check
              require: true
          topology:
            tolerance-surfaces:
              minArea: 1.0
            flatness:                     # a check a plugin supplies, declared
              path: //pub/qual/metrology:flatness
              maxDeviation: 0.05
          sim:
            stands:                       # a simulation (see 'partcad.simulation')
              path: //pub/feature/simulate/mujoco:mujoco
              validation: after["bodies"]["bracket"]["pos"][2] > -1
          other:
            budgets:                      # a check of another tool's (see 'OTHER')
              path: //pub/qual/lockwire:lockwire
              lockfile: lockwire.yaml

Under 'basic:', 'topology:' and 'other:' an entry is one of two things, told
apart by its name and by whether it says 'path:':

* the **parameters of a built-in check** -- its name is the check's, and every key
  is a parameter ('<object>.qual.basic.<test>.<param>: <value>'). The built-in
  checks are always applied; declaring parameters only tunes one, and a check that
  takes none ignores them;
* a **check a plugin supplies** -- an entry that says 'path:', the plugin by full
  path as a 'qual:' section of its package declares it (see 'partcad.qual.plugin').
  Its name is the object's to choose, and every key but the few in 'RESERVED' is a
  parameter handed to the plugin. A plugin check runs only where it is declared.

Under 'sim:' every entry is a simulation, whose plugin 'path:' names a package's
'simulation:' section (see 'partcad.simulation').

Before this section existed, three checks read their parameters from a key of
their own on the object -- 'interference:', 'connectivity:' and 'cmf:' (and
'validity:', which only ever said 'skip') -- and simulations were declared in
'simulate:', naming their plugin as 'simulation:'. All of those are still read:
a package in the index is not broken by PartCAD moving the place a setting
belongs. Where both say something, 'qual:' wins.
"""

import typing

from .. import logging as pc_logging

# The section of an object's declaration, and of a package's: on an object it is
# what this module reads; on a package it declares the qualification plugins the
# package supplies (see 'partcad.qual.plugin').
SECTION = "qual"

# The four subtypes, in the order they are presented.
BASIC = "basic"
TOPOLOGY = "topology"
SIM = "sim"
OTHER = "other"
SUBTYPES = (BASIC, TOPOLOGY, SIM, OTHER)

# What each subtype is called where a person reads it.
TITLES = {
    BASIC: "Basic",
    TOPOLOGY: "Topology",
    SIM: "Simulation",
    OTHER: "Other",
}

# The subtypes a plugin may supply a check of through a 'qual:' section. A
# simulation plugin is declared in a 'simulation:' section, as it always was.
PLUGIN_SUBTYPES = (BASIC, TOPOLOGY, OTHER)

# The key of an entry that names the plugin that runs it.
PATH = "path"

# The keys of a plugin check's entry that are about the entry rather than
# parameters handed to the plugin.
RESERVED = (PATH, "desc", "feature")

# Where the legacy spelling of a simulation named its plugin.
LEGACY_SIM_SECTION = "simulate"
LEGACY_SIM_PATH = "simulation"


def _final(shape_or_config) -> dict:
    """The declaration to read: a mapping as it is, or what a shape resolves to."""
    if isinstance(shape_or_config, dict):
        return shape_or_config
    if shape_or_config is None:
        return {}
    from ..shape_config import final_config

    config = final_config(shape_or_config)
    return config if isinstance(config, dict) else {}


def section(shape_or_config) -> dict:
    """The object's 'qual:' section; empty when it declares none, or something that is not a mapping."""
    config = _final(shape_or_config)
    value = config.get(SECTION)
    if value is None:
        return {}
    if not isinstance(value, dict):
        pc_logging.error("'%s' must be a mapping of subtypes (%s)" % (SECTION, ", ".join(SUBTYPES)))
        return {}
    unknown = [key for key in value if key not in SUBTYPES]
    for key in unknown:
        pc_logging.error("'%s: %s:' is not a subtype of qualification (%s)" % (SECTION, key, ", ".join(SUBTYPES)))
    return value


def subtype_section(shape_or_config, subtype: str) -> dict:
    """One subtype's mapping of 'qual:', as declared; empty when there is none."""
    value = section(shape_or_config).get(subtype)
    if value is None:
        return {}
    if not isinstance(value, dict):
        pc_logging.error("'%s: %s:' must be a mapping of names" % (SECTION, subtype))
        return {}
    return value


def params(shape_or_config, subtype: str, name: str, legacy: typing.Optional[str] = None) -> dict:
    """The parameters of the built-in check 'name' of 'subtype', as the object declares them.

    'qual: <subtype>: <name>:' over the check's legacy key ('legacy'), each
    key of the result one parameter. An entry that names a plugin ('path:')
    is a plugin's check that happens to share the name, and is not parameters.
    """
    config = _final(shape_or_config)
    result = {}
    if legacy:
        old = config.get(legacy)
        if isinstance(old, dict):
            result.update(old)
    entry = subtype_section(config, subtype).get(name)
    if isinstance(entry, dict) and PATH not in entry:
        result.update(entry)
    elif entry is not None and not isinstance(entry, dict):
        pc_logging.error("'%s: %s: %s:' must be a mapping of parameters" % (SECTION, subtype, name))
    return result


class Declaration:
    """One check a plugin supplies, as an object declares it under 'qual: <subtype>:'."""

    def __init__(self, subtype: str, name: str, config: dict):
        self.subtype = subtype
        self.name = name
        self.config = dict(config or {})
        self.path = self.config.get(PATH)
        self.desc = self.config.get("desc")
        # Every other key is the plugin's, as the object states it.
        self.params = {key: value for key, value in self.config.items() if key not in RESERVED}

    def __repr__(self) -> str:
        return "<qual %s %s: %s>" % (self.subtype, self.name, self.path)


def declared(shape_or_config, subtype: str, builtin_names=()) -> list:
    """The checks plugins supply that the object declares under 'qual: <subtype>:', in order.

    'builtin_names' are the names of the built-in checks of that subtype: an
    entry of one of those names is the check's parameters and not a declaration,
    unless it names a plugin, which a built-in check's name cannot be given to.
    """
    result = []
    for name, entry in subtype_section(shape_or_config, subtype).items():
        if not isinstance(entry, dict):
            continue
        if PATH not in entry:
            if name not in builtin_names:
                pc_logging.error(
                    "'%s: %s: %s:' names no built-in check and no plugin ('path:'): declare the plugin that runs it"
                    % (SECTION, subtype, name)
                )
            continue
        if name in builtin_names:
            pc_logging.error(
                "'%s: %s: %s:' names a plugin, but '%s' is a built-in check: give the plugin's check another name"
                % (SECTION, subtype, name, name)
            )
            continue
        result.append(Declaration(subtype, name, entry))
    return result


def simulations(shape_or_config) -> typing.List[typing.Tuple[str, dict]]:
    """The simulations an object declares, as (name, entry) pairs with the plugin under 'path'.

    'qual: sim:' first, then the legacy 'simulate:' section, whose plugin is
    named 'simulation:'; a name declared in both is the 'qual: sim:' one, and the
    other is reported rather than run twice.
    """
    config = _final(shape_or_config)
    result = []
    seen = set()
    for name, entry in subtype_section(config, SIM).items():
        seen.add(name)
        result.append((name, entry))
    legacy = config.get(LEGACY_SIM_SECTION)
    if legacy:
        if not isinstance(legacy, dict):
            pc_logging.error("The '%s' section must be a mapping of simulation names" % LEGACY_SIM_SECTION)
        else:
            for name, entry in legacy.items():
                if name in seen:
                    pc_logging.error(
                        "The simulation '%s' is declared under both '%s: %s:' and '%s:'; the first is run"
                        % (name, SECTION, SIM, LEGACY_SIM_SECTION)
                    )
                    continue
                if isinstance(entry, dict) and LEGACY_SIM_PATH in entry and PATH not in entry:
                    entry = dict(entry)
                    entry[PATH] = entry.pop(LEGACY_SIM_PATH)
                result.append((name, entry))
    return result


def subtypes_of(selection) -> typing.Tuple[str, ...]:
    """The subtypes a selection names, in presentation order: all of them for an empty one."""
    if not selection:
        return SUBTYPES
    if isinstance(selection, str):
        selection = [selection]
    chosen = set()
    for item in selection:
        item = {"simulation": SIM, "simulations": SIM}.get(item, item)
        if item not in SUBTYPES:
            raise ValueError("'%s' is not a subtype of qualification (%s)" % (item, ", ".join(SUBTYPES)))
        chosen.add(item)
    return tuple(subtype for subtype in SUBTYPES if subtype in chosen)
