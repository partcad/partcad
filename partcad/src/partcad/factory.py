#
# OpenVMP, 2023
#
# Author: PartCAD Inc. <support@partcad.org>
# Created: 2024-02-19
#
# Licensed under Apache License, Version 2.0.
#

from . import logging as pc_logging


class Factory:
    def __init__(self) -> None:
        pass


all = {
    "assembly": {},
    "part": {},
    "file": {},
    "provider": {},
}


def register(kind: str, t: str, factory_class: Factory.__class__):
    all[kind][t] = factory_class


def instantiate(kind: str, t: str, ctx, source_project, target_project, config):
    if t in all[kind]:
        # The return value is not always used
        return all[kind][t](ctx, source_project, target_project, config)
    else:
        pc_logging.error("Invalid %s type encountered: %s" % (kind, config))
