#
# PartCAD, 2025
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-09-07
#
# Licensed under Apache License, Version 2.0.
#

from async_lru import alru_cache
import typing

from . import logging as pc_logging


class Plugin:
    name: str
    desc: str
    config: dict[str, typing.Any] = None
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None
    errors: list[str]
    caps: dict[str, typing.Any] = None
    # Set to the reason once a query to this plugin has blown its deadline; see
    # plugin_factory_python.query_with_deadline. From then on the plugin is not
    # asked again, so one runaway script costs one deadline and not one per key.
    deadline_exceeded: typing.Optional[str] = None

    def __init__(self, name: str, config: dict[str, typing.Any] = {}, target_project_name=None):
        super().__init__()
        if target_project_name is None:
            self.name = name
            self.project_name = "."
        else:
            self.name = f"{target_project_name}:{name}"
            self.project_name = target_project_name
        self.config = config
        self.errors = []
        self.deadline_exceeded = None
        self.desc = config.get("desc", "")
        self.url = config.get("url", None)

        self.get_caps = alru_cache(maxsize=1, typed=True)(self.get_caps)

    def error(self, msg: str):
        mute = self.config.get("mute", False)
        if mute:
            self.errors.append(msg)
        else:
            pc_logging.error(msg)
