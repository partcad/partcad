#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

import sys

from packaging.specifiers import SpecifierSet

from . import consts
from . import exception as pc_exception
from . import logging as pc_logging
from . import sandbox_versions, telemetry


@telemetry.instrument()
class Configuration:
    """Holds the already-parsed configuration of a package.

    This class performs no I/O. Loading the configuration is the responsibility
    of the subclass (e.g. 'ProjectLocal' reads and renders 'partcad.yaml'),
    which then hands the result over explicitly:

        class ProjectLocal(Project):
            def __init__(self, ctx, name, path, ...):
                config_obj = <read, render and parse partcad.yaml>
                super().__init__(ctx, name, path=<dir>, config_obj=config_obj, ...)

    'path' and 'config_obj' are constructor parameters on purpose, rather than
    attributes the subclass is expected to have assigned before it calls
    'super().__init__()'. That implicit ordering contract is easy to get wrong:
    this constructor used to reset 'self.config_obj' here, which silently
    discarded the configuration the subclass had just parsed, and it used to
    read 'self.path', which made every subclass that had not assigned it yet
    fail with an AttributeError.

    Note that 'self.name' is not guaranteed to equal the 'name' argument on
    return: the root package may rename itself via the 'name' key of its
    configuration. Callers which registered the object under the requested name
    must re-key it afterwards - see 'Context.import_project()'.
    """

    name: str

    # What tells an old 'import:' (dependencies) from a new one (readers).
    #
    # 'type:' is the decisive one: the dependency schema *requires* it, and its
    # four values name transports. A reader declaration has no 'type' at all -
    # what it declares is 'path', 'kinds', 'extension' and so on - so the word
    # cannot mean both things by accident.
    DEPENDENCY_TRANSPORTS = frozenset({"git", "tar", "local", "external"})
    # The keys only a dependency has, so that an entry still being written -
    # a 'url:' with no 'type:' yet - is recognised for what it is rather than
    # read as a reader with an odd field.
    DEPENDENCY_ONLY_KEYS = frozenset(
        {"url", "relPath", "revision", "subfolder", "onlyInRoot", "cacheVersion", "includePaths", "plugin"}
    )

    @classmethod
    def _obsolete_import_entries(cls, section) -> list:
        """The names under 'import:' that describe a dependency, not a reader.

        Empty for a section that declares readers, which is what makes this safe
        to call on every package: the check costs one pass over a handful of
        keys and says nothing about a package using the section as it is meant
        to be used now.

        An entry that is neither - no marker, no reader fields - is left alone
        here and fails later, where the message can say what a reader
        declaration is missing.
        """
        if not isinstance(section, dict):
            return []
        obsolete = []
        for entry_name, entry in section.items():
            if not isinstance(entry, dict):
                continue
            if entry.get("type") in cls.DEPENDENCY_TRANSPORTS or (cls.DEPENDENCY_ONLY_KEYS & set(entry)):
                obsolete.append(entry_name)
        return obsolete

    def __init__(
        self,
        name: str,
        path: str,
        config_obj: dict | None = None,
        inherited_config: dict | None = None,
    ):
        self.name = name
        self.path = path
        self.config_dir = path
        self.config_obj = {} if config_obj is None else config_obj
        self.broken = False

        # Whether this package opted out of running here, and on which tag. Set
        # for real by 'Project', which is the first thing along this chain to
        # have a context - and therefore a tag set - to decide against. Defined
        # here so that every package has the attribute even when it never got
        # that far (a package whose 'partcad.yaml' would not parse, say).
        self.skipped = False
        self.skipped_by = None

        # 'declared_name' is the identity the package gives itself in its own
        # configuration. It is not necessarily where the package ended up being
        # loaded: the same package may be vendored into another package tree at
        # an arbitrary location. Capture it before the inherited configuration
        # is merged in and before 'name' is forced to the location below.
        self.declared_name = self.config_obj.get("name")

        # Merge the inherited configuration
        inherited_config = inherited_config or {}
        for key in inherited_config:
            if key not in self.config_obj:
                self.config_obj[key] = inherited_config[key]

        # The location is authoritative for every package except the root. The
        # root has no parent to derive a location from, so it adopts the name it
        # declares - that is what lets a package developed standalone use the
        # same package path its consumers will see it at. Captured before that
        # rename, because 'is this the package the user is standing in' is a
        # question the legacy-'import:' report below has to ask afterwards.
        is_root = name == consts.ROOT
        if is_root and self.declared_name:
            name = self.declared_name
            self.name = name
        else:
            self.config_obj["name"] = name

        if "render" not in self.config_obj or self.config_obj["render"] is None:
            self.config_obj["render"] = {}

        # 'import:' used to be the name of 'dependencies:', and for a while a
        # package that still used it was migrated here in silence. It cannot be
        # any more: 'import:' is now the section that declares object types a
        # package can read (see 'output.IMPORT'), so copying it into
        # 'dependencies' would take a perfectly good reader declaration and try
        # to fetch it as a package.
        #
        # The two are told apart by what the entries carry, and the markers are
        # decisive rather than a guess. 'type:' is *required* of a dependency
        # and its four values name transports; a reader declaration has no
        # 'type' at all, and could not use one of those words if it did. The
        # rest are the other transport-only keys, listed so that a
        # half-finished dependency is still recognised as one.
        #
        # Reported, never migrated: an automatic rewrite is what made the two
        # ambiguous, and doing it again with a better guess would only move the
        # day it goes wrong. So the section is dropped and said to be dropped.
        #
        # How loudly depends on whose package it is, and that is the only thing
        # the two cases differ in.
        #
        # The *root* package is the one the user is standing in and the one they
        # can fix, so it is an error and the package is broken: the command
        # exits non-zero and nothing loads out of a configuration PartCAD can no
        # longer read the way it was meant. That is how every other unreadable
        # 'partcad.yaml' is handled; see 'ProjectLocal.__init__'.
        #
        # An *imported* package is somebody else's -- very often reached through
        # the public index, several levels away from anything the user wrote --
        # so it is a warning naming the package, the entry and the fix, and the
        # package goes on being usable for everything else it declares. It has
        # to be: 'Context.import_project()' reports a broken import as an error
        # of its own, so marking it broken here would make one legacy package
        # anywhere in the index fail every command that merely walks past it.
        # What is lost is exactly what the section said -- those dependencies,
        # and whatever was underneath them.
        obsolete = self._obsolete_import_entries(self.config_obj.get("import"))
        if obsolete:
            report = pc_logging.error if is_root else pc_logging.warning
            report(
                "%s: 'import:' now declares object types this package can read, not its dependencies. "
                "The %s %s %s a dependency, not a reader, and %s ignored. "
                "Rename the section to 'dependencies:'."
                % (
                    name,
                    "entries" if len(obsolete) > 1 else "entry",
                    ", ".join("'%s'" % entry for entry in obsolete),
                    "describe" if len(obsolete) > 1 else "describes",
                    "are" if len(obsolete) > 1 else "is",
                )
            )
            self.broken = self.broken or is_root
            # Only the entries that gave themselves away. The check is per
            # entry, so the section is too: a package part-way through the
            # rename has a legacy dependency and a working reader side by side,
            # and dropping the whole mapping would take the reader with it --
            # leaving every object that uses it failing as an unknown type,
            # which says nothing about the section that caused it.
            import_section = self.config_obj["import"]
            for entry_name in obsolete:
                del import_section[entry_name]
            if not import_section:
                del self.config_obj["import"]

        # option: "partcad"
        # description: the version of PartCAD required to handle this package
        # values: string initializer for packaging.specifiers.SpecifierSet
        # default: None
        if "partcad" in self.config_obj:
            partcad_requirements = SpecifierSet(self.config_obj["partcad"])
            partcad_version = sys.modules["partcad"].__version__
            if partcad_version not in partcad_requirements:
                # TODO(clairbee): add better error and exception handling
                raise pc_exception.NeedsUpdateException(
                    "ERROR: Incompatible PartCAD version! %s does not satisfy %s"
                    % (partcad_version, partcad_requirements)
                )

        # option: "pythonVersion"
        # description: the version of python to use in sandboxed environments if any
        # values: string (e.g. "3.10")
        # default: sandbox_versions.DEFAULT_PYTHON_VERSION
        if "pythonVersion" in self.config_obj:
            python_version = self.config_obj["pythonVersion"]
            if not isinstance(python_version, str):
                # YAML parses an unquoted version like 3.11 as a float, which
                # breaks string use later and, worse, loses a trailing zero
                # (3.10 becomes 3.1). Recover the 'major.minor' string and
                # advise quoting; Python 3.1 has not existed for over a decade,
                # so a bare '3.1' is really '3.10'.
                pc_logging.warning('%s: quote "pythonVersion" as a string (e.g. "3.10")' % name)
                python_version = str(python_version)
                if python_version == "3.1":
                    python_version = "3.10"
            self.python_version = python_version
            # Kept apart from the resolved value below, because "this package
            # asked for 3.13" and "nobody asked, so it got the default" are
            # different answers and one caller has to tell them apart: an output
            # implementation runs on the interpreter the package that ships it
            # asked for, and on a fixed default otherwise (see
            # output.Implementation.python_version()).
            self.python_version_declared = python_version
        else:
            # NOT the interpreter PartCAD itself is running on, which is what
            # this used to be. Nothing was gained by matching it: under 'conda'
            # the sandbox is built from scratch at whatever version is asked
            # for and the host interpreter is never reused, and under 'none'
            # the version is ignored altogether (runtime_python_none takes
            # whatever 'python' is on PATH). All it did was make the sandbox a
            # property of how PartCAD happened to be installed - so the same
            # package rendered on a different interpreter for each developer,
            # changed under one of them when they upgraded their Python, and,
            # in the standalone bundle, followed whatever Python the release
            # was frozen with. Pinning it here makes a sandbox as reproducible
            # as the stack that goes into it.
            self.python_version = sandbox_versions.DEFAULT_PYTHON_VERSION
            self.python_version_declared = None

        # option: "dockerImage"
        # description: the image this package's sandboxes are built from, for
        #              whoever is using the "docker" sandbox
        # values: string (e.g. "ghcr.io/example/solver:1a2b3c4d")
        # default: None, meaning PartCAD's own base image for the Python version
        #
        # Declared by a package that needs something pip cannot install -- a
        # native executable, a library with no wheel for some platform. It does
        # NOT excuse the package from declaring its "pythonRequirements": an
        # image says where the package runs best, not where it runs at all, and
        # a host that has the native pieces installed runs it in a conda or venv
        # sandbox like any other package.
        #
        # Kept apart from anything resolved, for the reason "pythonVersion" is:
        # an output implementation runs in the image the package that *ships* it
        # named, and a caller asking for a part has no opinion worth reading.
        self.docker_image_declared = self.config_obj.get("dockerImage")
        if self.docker_image_declared is not None and not isinstance(self.docker_image_declared, str):
            pc_logging.warning('%s: "dockerImage" must be a string naming an image' % name)
            self.docker_image_declared = str(self.docker_image_declared)

        # option: "javascriptVersion"
        # description: the major version of Node.js to use in sandboxed
        #              environments if any
        # values: string (e.g. "22")
        # default: None, meaning sandbox_versions.DEFAULT_NODE_VERSION
        if "javascriptVersion" in self.config_obj:
            # Node.js is versioned by major line and that is the granularity a
            # sandbox is provisioned at, so an unquoted 22 (which YAML parses as
            # an int) and a "22.11.0" both name the same thing. No warning here,
            # unlike pythonVersion: there is no trailing digit to lose.
            self.javascript_version = sandbox_versions.node_major_version(str(self.config_obj["javascriptVersion"]))
        else:
            self.javascript_version = None

        # option: "chili3dVersion"
        # description: the version of Chili3D to install into the sandbox this
        #              package's Chili3D parts are rendered in
        # values: string - an exact version ("1.1.2"), or any range or tag npm
        #         accepts ("^1.1", "latest")
        # default: None, meaning sandbox_versions.DEFAULT_CHILI3D_VERSION
        #
        # Unlike the CAD libraries on the Python side, this really is the
        # package's to choose: a Node.js environment is identified by the set of
        # dependencies it holds, so a package on its own Chili3D gets its own
        # environment and changes nothing for anybody else.
        chili3d_version = self.config_obj.get("chili3dVersion")
        self.chili3d_version = None if chili3d_version is None else str(chili3d_version)

        # option: "unless"
        # description: the tags this package does not work under. It is skipped
        #              wherever one of them is a tag of the context - see
        #              'partcad.tags' and 'Project.__init__', which is where the
        #              decision is actually made (this class has no context, and
        #              therefore no tags, to make it against).
        # values: a tag, or a list of tags
        # default: none

        # option: "manufacturable"
        # description: whether the objects in this package are designed for manufacturing by default
        # values: boolean
        # default: True
        if "manufacturable" in self.config_obj:
            self.is_manufacturable = bool(self.config_obj["manufacturable"])
        else:
            self.is_manufacturable = True
