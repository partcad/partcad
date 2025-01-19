#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

import os

from . import logging as pc_logging
from .part_factory_file import PartFactoryFile
from .runtime_python import PythonRuntime


class PartFactoryPython(PartFactoryFile):
    runtime: PythonRuntime
    cwd: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config,
        can_create=False,
        python_version=None,
        extension=".py",
    ):
        super().__init__(
            ctx,
            source_project,
            target_project,
            config,
            extension=extension,
            can_create=can_create,
        )
        self.cwd = config.get("cwd", None)

        if python_version is None:
            # TODO(clairbee): stick to a default constant or configured version
            python_version = self.project.python_version
        self.runtime = self.ctx.get_python_runtime(python_version)
        self.session = self.runtime.get_session(source_project.name)

    def post_create(self) -> None:
        for dep in self.config.get("dependencies", []):
            self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
        super().post_create()

    async def prepare_python(self):
        """
        This method is called by child classes
        to prepare the Python environment
        before instantiating the part.
        """

        # Install dependencies of this package
        # DO NOT COMMIT
        await self.runtime.prepare_for_package(self.project, session=self.session)
        await self.runtime.prepare_for_shape(self.config, session=self.session)

    def info(self, part):
        info: dict[str, object] = part.shape_info(self.ctx)
        info.update(
            {
                "runtime_version": self.runtime.version,
                "runtime_path": self.runtime.path,
            }
        )
        return info

    async def instantiate(self, part):
        await super().instantiate(part)
