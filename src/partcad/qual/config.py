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
their own on the object -- 'interference:', 'connectivity:' and 'cmf:' -- and
simulations were declared in 'simulate:', naming their plugin as 'simulation:'.
Those are the old spellings ('LEGACY'), and they are still read, as what the
section would say where it says nothing itself, with a warning naming what to
write instead. They stay until the index's packages have moved to 'qual:' and a
release that reads it is out -- PartCAD's order for retiring anything packages
say (see "Branches, releases and breaking changes" in the contributing guide) --
and then go, the warning with them.
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

# The keys of an object's declaration that 'qual:' replaced, and where each lives
# now: (subtype, the check's name), or the whole subtype for 'simulate:', whose
# entries are simulations. Read as what 'qual:' says where it says nothing
# itself, with a warning naming what to write instead (see the module's
# docstring for how long).
LEGACY = {
    "simulate": (SIM, None),
    "interference": (TOPOLOGY, "interference"),
    "connectivity": (BASIC, "connectivity"),
    "cmf": (BASIC, "cmf"),
}

# What a simulation named its plugin as, under 'simulate:'.
LEGACY_SIMULATION = "simulation"


# What has been said about a declaration's mistakes in this command: every check
# of every object reads 'qual:', and one mistake said once per check is the same
# sentence a dozen times. Keyed on the command, so that a warm daemon says it
# again for the next command rather than never again (see 'plugin.begin_command').
_reported: set = set()


def _say(message: str, log) -> None:
    from ..plugin import command_generation

    key = (command_generation(), message)
    if key in _reported:
        return
    if len(_reported) > 4096:
        _reported.clear()
    _reported.add(key)
    log(message)


def _error(message: str) -> None:
    _say(message, pc_logging.error)


def _warn(message: str) -> None:
    _say(message, pc_logging.warning)


def _final(shape_or_config) -> dict:
    """The declaration to read: a mapping as it is, or what a shape resolves to."""
    if isinstance(shape_or_config, dict):
        return shape_or_config
    if shape_or_config is None:
        return {}
    from ..shape_config import final_config

    config = final_config(shape_or_config)
    return config if isinstance(config, dict) else {}


def _spelled_now(key: str) -> str:
    subtype, name = LEGACY[key]
    if name is None:
        return "'%s: %s:', each simulation naming its plugin as '%s:' rather than '%s:'" % (
            SECTION,
            subtype,
            PATH,
            LEGACY_SIMULATION,
        )
    return "'%s: %s: %s:'" % (SECTION, subtype, name)


def legacy(config: dict) -> typing.List[str]:
    """What an object's declaration still says the way it was said before 'qual:', as sentences saying what to write."""
    return [
        "'%s:' is the old spelling of %s, and is read for now: write that instead, since the old one is going away"
        % (key, _spelled_now(key))
        for key in LEGACY
        if isinstance(config, dict) and config.get(key) is not None
    ]


def _with_legacy(value: dict, config: dict) -> dict:
    """'value', the 'qual:' section, with what the old spellings say wherever it says nothing itself."""
    merged = dict(value)
    for key, (subtype, name) in LEGACY.items():
        old = config.get(key)
        if old is None:
            continue
        target = merged.get(subtype)
        if target is None:
            target = {}
        elif not isinstance(target, dict):
            # Wrong as it is, and said so by 'subtype_section()'.
            continue
        else:
            target = dict(target)
        if name is not None:
            target.setdefault(name, old)
        elif isinstance(old, dict):
            for simulation, entry in old.items():
                if simulation in target:
                    continue
                if isinstance(entry, dict) and LEGACY_SIMULATION in entry and PATH not in entry:
                    entry = dict(entry)
                    entry[PATH] = entry.pop(LEGACY_SIMULATION)
                target[simulation] = entry
        merged[subtype] = target
    return merged


def section(shape_or_config) -> dict:
    """The object's 'qual:' section; empty when it declares none, or something that is not a mapping.

    With what the old spellings ('LEGACY') say, where it says nothing itself.
    """
    config = _final(shape_or_config)
    name = config.get("name") if isinstance(config, dict) else None
    value = config.get(SECTION)
    if value is None:
        value = {}
    elif not isinstance(value, dict):
        _error("'%s' must be a mapping of subtypes (%s)" % (SECTION, ", ".join(SUBTYPES)))
        value = {}
    else:
        unknown = [key for key in value if key not in SUBTYPES]
        for key in unknown:
            _error("'%s: %s:' is not a subtype of qualification (%s)" % (SECTION, key, ", ".join(SUBTYPES)))
    sentences = legacy(config)
    if sentences:
        for sentence in sentences:
            _warn("%s%s" % ("%s: " % name if name else "", sentence))
        value = _with_legacy(value, config)
    return value


def subtype_section(shape_or_config, subtype: str) -> dict:
    """One subtype's mapping of 'qual:', as declared; empty when there is none."""
    value = section(shape_or_config).get(subtype)
    if value is None:
        return {}
    if not isinstance(value, dict):
        _error("'%s: %s:' must be a mapping of names" % (SECTION, subtype))
        return {}
    return value


def params(shape_or_config, subtype: str, name: str) -> dict:
    """The parameters of the built-in check 'name' of 'subtype', as the object declares them.

    'qual: <subtype>: <name>:', each key one parameter. An entry that names a
    plugin ('path:') is a plugin's check that happens to share the name, and is
    not parameters.
    """
    entry = subtype_section(_final(shape_or_config), subtype).get(name)
    if isinstance(entry, dict) and PATH not in entry:
        return dict(entry)
    if entry is not None and not isinstance(entry, dict):
        _error("'%s: %s: %s:' must be a mapping of parameters" % (SECTION, subtype, name))
    return {}


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
                _error(
                    "'%s: %s: %s:' names no built-in check and no plugin ('path:'): declare the plugin that runs it"
                    % (SECTION, subtype, name)
                )
            continue
        if name in builtin_names:
            _error(
                "'%s: %s: %s:' names a plugin, but '%s' is a built-in check: give the plugin's check another name"
                % (SECTION, subtype, name, name)
            )
            continue
        result.append(Declaration(subtype, name, entry))
    return result


def simulations(shape_or_config) -> typing.List[typing.Tuple[str, dict]]:
    """The simulations an object declares under 'qual: sim:', as (name, entry) pairs, in order."""
    return list(subtype_section(_final(shape_or_config), SIM).items())


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
