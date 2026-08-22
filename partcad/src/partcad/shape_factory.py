#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#

from . import factory

from .file_factory import FileFactory
from .port import WithPorts
from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
class ShapeFactory(factory.Factory):
    fileFactory: FileFactory

    # The Python a factory's sandbox runs, for the factories whose sandbox is
    # fixed rather than resolved from the package's configuration. None means
    # this factory produces its shape without a sandbox at all - an alias, an
    # enrich, an assembly - and so has no environment to cache under.
    PYTHON_SANDBOX_VERSION: str | None = None

    def __init__(self, ctx, project, config) -> None:
        super().__init__()

        self.ctx = ctx
        self.project = project
        self.config = config

        if "manufacturable" not in config:
            config["manufacturable"] = project.is_manufacturable

        if "fileFrom" in config:
            self.fileFactory = factory.instantiate("file", config["fileFrom"], ctx, project, project, config)
        else:
            self.fileFactory = None

        self.with_ports = WithPorts(config["name"], project, config)

    def environment_cache_key(self) -> str | None:
        """The environment this factory produces its shape in, or None.

        Every shape built by a sandboxed interpreter belongs to the versions
        that built it, so the environment is part of what it is cached under
        (see Shape.set_environment_cache_key). The default covers the factories
        whose sandbox is a fixed interpreter carrying the stack PartCAD pins;
        the ones that resolve either from configuration - the script types -
        override it.
        """
        if self.PYTHON_SANDBOX_VERSION is None:
            return None
        return sandbox_versions.environment_cache_key(
            "python", self.PYTHON_SANDBOX_VERSION, sandbox_versions.PINNED_REQUIREMENTS
        )

    def apply_environment_cache_key(self, shape) -> None:
        """Stamp the environment onto a shape as it is created.

        Called from every shape kind's '_create()', so a factory only has to say
        what its environment is and never has to remember to record it. Must
        happen before the hash is used, which creation time guarantees.
        """
        environment_cache_key = self.environment_cache_key()
        if environment_cache_key is not None:
            shape.set_environment_cache_key(environment_cache_key)

    def info(self, shape):
        """This is the default implementation of the get_info method for factories."""
        info: dict = shape.shape_info(self.ctx)
        if "url" in self.project.config_obj and self.project.config_obj["url"] is not None:
            info["Url"] = self.project.config_obj["url"]
        if "importUrl" in self.project.config_obj and self.project.config_obj["importUrl"] is not None:
            info["ImportUrl"] = self.project.config_obj["importUrl"]
        info["Path"] = self.project.name
        return info
