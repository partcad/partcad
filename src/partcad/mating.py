#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

from .interface import Interface


class Mating:
    """A mating between two interfaces."""

    source: Interface
    target: Interface
    desc: str
    count: int
    self_screw: bool

    source_port_selector: str
    target_port_selector: str

    def __init__(
        self,
        source: Interface,
        target: Interface,
        config: dict = {},
        reverse: bool = False,
    ):
        if config is None:
            config = {}
        elif isinstance(config, str):
            config = {config: None}
        elif isinstance(config, list):
            config = {c: None for c in config}
        elif not isinstance(config, dict):
            raise ValueError("Invalid mating configuration")

        self.source = source
        self.target = target
        self.desc = config["desc"] if "desc" in config else ""
        # Whether a thread gets *cut* by making this connection rather than
        # matched, which is what lets the two ends carry different threads - or
        # one of them none at all. Declared here rather than on either
        # interface because it is true of the pairing and not of the part: a
        # self-tapping screw cuts its thread in the pilot hole it is driven
        # into, and cuts nothing on its way through a clearance hole.
        self.self_screw = bool(config.get("selfScrew", False)) if isinstance(config, dict) else False

        if "sourcePortSelector" in config:
            if reverse:
                self.target_port_selector = config["sourcePortSelector"]
            else:
                self.source_port_selector = config["sourcePortSelector"]
        else:
            self.source_port_selector = None

        if "targetPortSelector" in config:
            if reverse:
                self.source_port_selector = config["targetPortSelector"]
            else:
                self.target_port_selector = config["targetPortSelector"]
        else:
            self.target_port_selector = None
