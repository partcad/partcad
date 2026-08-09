#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2023-12-30
#
# Licensed under Apache License, Version 2.0.
#

import os

from .part_factory_file import PartFactoryFile
from .runtime_python import PythonRuntime
from . import sandbox_versions
from . import telemetry


@telemetry.instrument()
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

    def environment_requirements(self) -> list[str]:
        """Everything installed into the sandbox this part renders in.

        The CAD stack PartCAD supplies comes first: 'once()' preinstalls all of
        it into every sandbox, and 'reconcile_requirement()' holds a package to
        those versions, so a bump moves every Python part's shape - which is the
        point, since those versions are what produced it.

        The package's and the part's own requirements are reconciled the same
        way the installer reconciles them, so that a requirement PartCAD would
        override does not key as though it had been honored.
        """
        requirements = list(sandbox_versions.PINNED_REQUIREMENTS)
        requirements += PythonRuntime.package_requirements(self.project)
        requirements += PythonRuntime.shape_requirements(self.config)
        return [sandbox_versions.reconcile_requirement(requirement)[0] for requirement in requirements]

    def post_create(self) -> None:
        for dep in self.config.get("dependencies", []):
            self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
        self.part.set_environment_cache_key(
            sandbox_versions.environment_cache_key("python", self.runtime.version, self.environment_requirements())
        )
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
                "sandbox_version": self.runtime.version,
                "sandbox_path": self.runtime.path,
            }
        )
        return info

    async def instantiate(self, part):
        await super().instantiate(part)
