#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging
from . import telemetry
from .software_factory_file import SoftwareFactoryFile


@telemetry.instrument()
class SoftwareFactoryRaw(SoftwareFactoryFile):
    """The default software type: a file PartCAD carries and identifies.

    PartCAD neither parses it nor transforms it, and it deliberately guesses no
    extension for it - a firmware image is as likely to be a '.bin' as a '.img'
    or no extension at all, so the name of the object is the whole default and
    anything else is spelled out with 'path'.

    The types that will join it are not other kinds of object: they are this one
    plus a specific firmware flashing procedure (a '.uf2' copied to a mounted
    bootloader volume, a '.hex' pushed with 'avrdude', a '.dfu' with
    'dfu-util'). They belong beside this class, sharing the file plumbing in
    'SoftwareFactoryFile', so that whatever a package declares its software as,
    the answer to "which file is it" is reached the same way.
    """

    def __init__(self, ctx, source_project, target_project, config, can_create=False):
        with pc_logging.Action("InitSoftware", target_project.name, config["name"]):
            super().__init__(
                ctx,
                source_project,
                target_project,
                config,
                extension="",
                can_create=can_create,
            )
            self._create(config)
