#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.

import os

from .user_config import user_config


class Runtime:
    @staticmethod
    def get_internal_state_dir():
        return os.path.join(
            user_config.internal_state_dir,
            "sandbox",
        )

    def __init__(self, ctx, name):
        self.ctx = ctx
        self.name = name
        self.path = os.path.join(
            Runtime.get_internal_state_dir(),
            "pc-" + name,  # Leave "pc-" for UX (e.g. in VS Code)
        )
        self.initialized = os.path.exists(self.path)
