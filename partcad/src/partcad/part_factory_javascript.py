#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Common base for parts produced by a script running in a Node.js sandbox.

The JavaScript twin of part_factory_python: it resolves which Node.js sandbox
the part renders in, opens the session that scopes that package's dependency
tree, and installs whatever the package and the part declare before the wrapper
is run.
"""

import os

from .part_factory_file import PartFactoryFile
from .runtime_javascript import JavaScriptRuntime
from . import telemetry


@telemetry.instrument()
class PartFactoryJavaScript(PartFactoryFile):
    runtime: JavaScriptRuntime
    cwd: str

    def __init__(
        self,
        ctx,
        source_project,
        target_project,
        config,
        can_create=False,
        javascript_version=None,
        extension=".js",
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

        if javascript_version is None:
            javascript_version = self.project.javascript_version
        self.runtime = self.ctx.get_javascript_runtime(javascript_version)
        self.session = self.runtime.get_session(source_project.name)

    def post_create(self) -> None:
        for dep in self.config.get("dependencies", []):
            self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
        super().post_create()

    async def prepare_javascript(self):
        """
        This method is called by child classes
        to prepare the JavaScript environment
        before instantiating the part.
        """
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
