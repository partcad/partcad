#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import typing

from . import factory
from . import telemetry
from .software import Software


@telemetry.instrument()
class SoftwareFactory(factory.Factory):
    """The base of every 'software' factory.

    Deliberately not a 'ShapeFactory': software has no geometry, so none of what
    that class exists for - ports, manufacturability, the sandbox environment a
    shape is built in and cached under - applies here. What is shared with the
    shape factories is the *file* plumbing, and that is shared by following the
    same shape of code rather than by inheriting a class built for shapes.
    """

    name: str
    orig_name: str
    path: typing.Optional[str] = None
    software: Software

    def __init__(self, ctx, source_project, target_project, config) -> None:
        super().__init__()

        self.ctx = ctx
        self.project = source_project
        self.target_project = target_project
        self.config = config
        self.name = config["name"]
        self.orig_name = config["orig_name"]

    def _create_software(self, config) -> Software:
        software = Software(self.target_project.name, config)
        software.path = self.path
        software.prepare_async = lambda: self.prepare_async(software)
        software.info = lambda: self.info(software)
        return software

    def _create(self, config) -> None:
        self.software = self._create_software(config)
        self.target_project.register_object("software", self.name, self.software)
        self.post_create()

    def post_create(self) -> None:
        # A base class catch-all, as in the shape factories.
        pass

    async def prepare_async(self, software) -> None:
        """Put the file this object stands for on disk, if it is not there yet."""
        return None

    def info(self, software) -> dict:
        info = software.software_info()
        config_obj = self.project.config_obj or {}
        if config_obj.get("url") is not None:
            info["Url"] = config_obj["url"]
        if config_obj.get("importUrl") is not None:
            info["ImportUrl"] = config_obj["importUrl"]
        return info
