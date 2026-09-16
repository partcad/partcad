#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#

from . import factory, sandbox_versions
from . import software as pc_software
from . import step_metadata, telemetry
from .file_factory import FileFactory
from .port import WithPorts


@telemetry.instrument()
class ShapeFactory(factory.Factory):
    fileFactory: FileFactory

    # The Python a factory's sandbox runs, for the factories whose sandbox is
    # fixed rather than resolved from the package's configuration. None means
    # this factory produces its shape without a sandbox at all - an alias, an
    # enrich, an assembly - and so has no environment to cache under.
    PYTHON_SANDBOX_VERSION: str | None = None

    # The format of the file this factory reads, for the formats 'step_metadata'
    # knows how to read metadata out of. None - which is nearly every factory -
    # means there is no file to ask, or nothing here that can read it, and the
    # shape's info is what it always was.
    #
    # Named as a *format* rather than as a type, for the same reason
    # 'TOLERANCE_FILE_FORMAT' is: 'kicad' produces a STEP file some other way
    # and is read like one, without having to be named a second time.
    METADATA_FILE_FORMAT: str | None = None

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

        # The software this shape ships with, resolved against the package that
        # *authored* the declaration. Resolved here because this is the only
        # place that knows which package that is: an alias hands its source's
        # configuration on unchanged and an enrich copies it, so by the time a
        # bill of materials reads it there is no telling where a bare 'firmware'
        # was written. Left alone when it is already there, which is what makes
        # a reference survive being handed on (see 'software.RESOLVED_KEY').
        if pc_software.RESOLVED_KEY not in config:
            resolved = pc_software.declared_software_refs(project.name, config)
            if resolved:
                config[pc_software.RESOLVED_KEY] = resolved

        self.with_ports = WithPorts(config["name"], project, config)

    async def prepare_async(self, shape) -> None:
        """Fetch what this shape needs before its cache key can be computed.

        Overridden by the factories that have something to fetch: the file
        factories download whatever 'fileFrom' points at, and the factories
        that reference another object (alias, enrich, compound, assy) resolve
        it, which loads the package holding it. The default is to do nothing -
        a shape defined entirely by its own package has nothing to fetch.
        """
        return None

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
        info.update(self.file_info())
        return info

    def file_info(self) -> dict:
        """What the file this shape is read from states about itself.

        Its layers, the products it names, and the properties hung on those -
        see 'step_metadata'. Empty for a factory that declares no
        'METADATA_FILE_FORMAT', for one whose file is not on disk yet, and for a
        file that states none of it.

        Read here rather than carried on the shape, because none of it is a
        property of the shape: a part read out of a STEP file is one solid out
        of a file that may name twenty, and what the file says about the other
        nineteen is still what 'pc info' on that file's part should show. The
        file is on disk by the time this is asked - 'shape_info' has already
        built the shape - and reading it is a scan over bytes with no CAD kernel
        behind it.
        """
        if self.METADATA_FILE_FORMAT is None:
            return {}
        metadata = step_metadata.of_file(self.METADATA_FILE_FORMAT, getattr(self, "path", None))
        return step_metadata.as_info(metadata)
