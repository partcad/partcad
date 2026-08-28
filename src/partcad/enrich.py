#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""What an 'enrich' declaration points at.

Shared by the part and the sketch enrich factories, which differ in nothing
here, and kept out of both so that the answer cannot come out differently for a
part and for a sketch.
"""

from . import logging as pc_logging
from .user_config import user_config
from .utils import format_parameterized_name, get_child_project_path

# The properties of an 'enrich' declaration that describe the reference itself
# rather than the object it resolves to: which object is being enriched, which
# package it is in, and how it is to be parametrized. They say nothing once the
# reference has been resolved - what the resolved object records instead is
# 'source', the fully qualified name of the instance behind it - so they are
# not carried onto it. Everything else an enrich declares ('desc', 'offset',
# 'scale', the render settings) describes the object it produces and is kept.
#
# 'package' and 'project' are two spellings of the same thing, and 'path' and
# 'type' come from the instance, which is what is actually built.
ENRICH_ONLY_PROPERTIES = frozenset({"type", "path", "orig_name", "source", "project", "package", "with"})

# What belongs to the object an enrich points at and to nothing else. An
# 'aliases:' entry is a name the *source's* package publishes for the source,
# and a package does not gain a part called 'box' because one of its enriches
# happens to point at something that has one. The enrich publishes its own
# aliases if it declares them - that is an ordinary property of the declaration,
# and it is kept.
SOURCE_ONLY_PROPERTIES = frozenset({"aliases"})

# What the object an enrich points at has already applied to itself by the time
# it hands its geometry back: 'get_wrapped()' places and scales what a factory
# produced, and the instance now materializes itself (see 'PartFactoryAlias').
# So an enrich reports the instance's parameters but not its placement, or it
# would apply it a second time. An enrich's own 'offset'/'scale' still apply,
# on top of what the instance produced.
INSTANCE_APPLIED_PROPERTIES = frozenset({"offset", "scale"})

# What an enrich cannot act on: everything that says how an object is *built*.
# An enrich does not build anything - it points at an instance of an object
# another declaration defines, and that declaration is what says where the file
# is, which interpreter and packages it is built with, and what it is built
# from. Declaring one of these on an enrich has never had an effect worth
# relying on, and now has none at all, so it is reported rather than ignored in
# silence.
#
# 'parameters' is here for the same reason: an enrich states which values it
# wants through 'with', and redeclaring the parameters of the object it points
# at does not change which instance of it that is.
#
# Deliberately a list of what is ignored rather than of what is honoured: a key
# that is neither describes the object an enrich produces ('desc', 'offset',
# the render settings), and those are carried onto it. Something new that
# belongs on this side has to be added here.
ENRICH_IGNORED_PROPERTIES = frozenset(
    {
        # Where the object's own definition is
        "path",
        "fileFrom",
        "fileUrl",
        "url",
        "dependencies",
        # What it is built with
        "requirements",
        "pythonRequirements",
        "javascriptRequirements",
        "javascriptVersion",
        "chili3dVersion",
        # How the script that builds it is run
        "cwd",
        "showObject",
        "method",
        "patch",
        # What the types that build one object out of another take
        "sketch",
        "depth",
        "axis",
        "ratio",
        # What a sketch is made of, and how a file-backed one is read
        "circle",
        "rectangle",
        "square",
        "inner",
        "include",
        "exclude",
        "flip-y",
        "ignore-visibility",
        "tolerance",
        "use-faces",
        "use-wires",
        # Asked for through 'with', not by redeclaring them
        "parameters",
    }
)


def warn_about_ignored_properties(target_project, config, source: str) -> None:
    """Report the properties of this enrich that nothing will act on.

    A warning and not an error: the declaration is still usable, and the object
    it produces is exactly the one it would have produced without them.
    """
    ignored = sorted(set(config) & ENRICH_IGNORED_PROPERTIES)
    if not ignored:
        return
    pc_logging.warning(
        "The enrich '%s:%s' ignores %s: what it points at is built as '%s' declares it"
        % (
            target_project.name,
            config["name"],
            ", ".join("'%s'" % name for name in ignored),
            source,
        )
    )


def adopt_source_config(obj, source, source_name: str) -> None:
    """Have this enrich report the instance it resolved to.

    The parameters it asked for are what a reader wants back from it - 'pc
    info' and the assemblies that use it read them from here - while what the
    enrich declares itself describes this object and not the instance it shares
    with every other enrich that asks for the same values.

    Done while the object is prepared rather than while it is instantiated,
    because a shape that comes out of the cache is never instantiated, and what
    it reports cannot depend on whether it was built or read back.

    The source's *final* config, so that an enrich pointing at an alias - or at
    a chain of them - reports what is at the end of it rather than the
    reference in the middle. Not its placement: the instance applies its own
    when it materializes itself, and this object's own applies on top of what
    came back.
    """
    enrich_config = obj.config
    obj.config = {
        key: value
        for key, value in source.get_final_config().items()
        if key not in INSTANCE_APPLIED_PROPERTIES and key not in SOURCE_ONLY_PROPERTIES
    }
    for prop_to_copy in enrich_config:
        if prop_to_copy in ENRICH_ONLY_PROPERTIES:
            continue
        obj.config[prop_to_copy] = enrich_config[prop_to_copy]
    obj.config["source"] = source_name
    # Kept in step with it: a consumer that walks the stored configuration
    # prefers 'source_resolved' where it is present ('pc convert'), and the one
    # the declaration carried was written before the source was resolved again
    # (see 'resolve_source_again').
    obj.config["source_resolved"] = source_name
    obj.config["orig_name"] = obj.name
    obj.config["name"] = enrich_config["name"]


def enriched_source_name(source_project, target_project, config) -> str:
    """'<package>:<object>;<param>=<value>,...' - the instance an enrich asks for.

    Which object is being enriched is spelled the same way an alias spells it:
    'source' names it, and 'package'/'project' say which package it is in, with
    the object's own name as the default when only a package is given. That is
    the shorthand that made enriching an object of another package replace it -
    the name defaulted to the source object's own, and the enriched instance
    used to be registered in the source package under it.

    The parameters come from three places, each overriding the one before it:
    the source name may carry some of its own ('cube;width=20.0'), 'with' is
    the shorthand an enrich is normally written with, and the user's own
    configuration overrides both for the object it names - the same override
    'Configuration.normalize' applies to an object that declares its parameters
    outright, which for an enrich has to be applied here instead, since what an
    enrich declares is which instance it wants rather than the parameters
    themselves.
    """
    if "source" in config:
        source_name = config["source"]
    else:
        source_name = config["name"]
        if "project" not in config and "package" not in config:
            raise Exception("Enrich needs either the source object name or the source project name")

    if "project" in config or "package" in config:
        project_name = config["project"] if "project" in config else config["package"]
        if project_name == "this" or project_name == "":
            project_name = source_project.name
        elif not project_name.startswith("//"):
            # Resolve the project name relative to the target project
            project_name = get_child_project_path(target_project.name, project_name)
        source_name = project_name + ":" + source_name
    elif ":" not in source_name:
        source_name = source_project.name + ":" + source_name
    else:
        # Written as a reference of its own (':widget', '../other:widget'), so
        # the package that authored it is what it is relative to. Spelled out
        # here rather than left to the alias this hands the work to, because the
        # name is also what gets recorded as 'source_resolved', and a consumer
        # that walks the stored configuration has no package to read it against.
        source_name = source_project.normalize(source_name)

    parameters = dict(config.get("with") or {})
    parameters.update(user_config.parameter_config.to_dict().get(f"{target_project.name}:{config['name']}", {}))
    return format_parameterized_name(source_name, parameters)


def resolve_source_again(factory, declaration, source_attribute: str) -> None:
    """Point this enrich at whatever its declaration now names.

    The user's own parameter overrides ('pc.user_config.parameter_config') can
    arrive after the package has been loaded: the CLI reads them from the
    command line, and a program using PartCAD as a library sets them against a
    context it already has. An override on an enrich says which instance of the
    source it wants and not merely what that instance reports, so the name is
    worked out once more here - where everything has been declared and nothing
    has been resolved yet - rather than only while the factory was constructed.

    Constructing it still resolves the source, because that is what makes a
    chain of enriches and aliases work in any order, and because 'pc convert'
    reads the resolved name off the declaration without preparing anything.
    """
    source = enriched_source_name(factory.project, factory.target_project, declaration)
    if source == factory.source:
        return
    factory.source = source
    # The package name is what precedes the first ':' - it is fully qualified
    # and holds none of its own - and the rest is the object, parameters and
    # all.
    factory.source_project_name, _, object_name = source.partition(":")
    setattr(factory, source_attribute, object_name)
    declaration["source_resolved"] = source
