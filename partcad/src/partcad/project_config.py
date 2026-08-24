#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-08-19
#
# Licensed under Apache License, Version 2.0.

from packaging.specifiers import SpecifierSet
import sys

from . import consts
from . import logging as pc_logging
from . import exception as pc_exception
from . import sandbox_versions
from . import telemetry


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
        # same package path its consumers will see it at.
        if name == consts.ROOT and self.declared_name:
            name = self.declared_name
            self.name = name
        else:
            self.config_obj["name"] = name

        if not "render" in self.config_obj or self.config_obj["render"] is None:
            self.config_obj["render"] = {}

        # Backward compatibility for "import" -> "dependencies" renaming
        if "import" in self.config_obj and "dependencies" not in self.config_obj:
            pc_logging.warning(
                f"{name}: 'import' key is deprecated and will be removed in future versions. Use 'dependencies' instead.",
            )
            self.config_obj["dependencies"] = self.config_obj["import"]
            del self.config_obj["import"]  # Clean up old key

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
        # default: <The major and minor version of the current interpreter>
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
            # asked for 3.13" and "nobody asked, so whatever interpreter PartCAD
            # happens to run on" are different answers and one caller has to tell
            # them apart: an output implementation runs on the interpreter the
            # package that ships it asked for, and on a fixed default otherwise
            # (see output.Implementation.python_version()).
            self.python_version_declared = python_version
        else:
            self.python_version = "%d.%d" % (
                sys.version_info.major,
                sys.version_info.minor,
            )
            self.python_version_declared = None

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

        # option: "manufacturable"
        # description: whether the objects in this package are designed for manufacturing by default
        # values: boolean
        # default: True
        if "manufacturable" in self.config_obj:
            self.is_manufacturable = bool(self.config_obj["manufacturable"])
        else:
            self.is_manufacturable = True
