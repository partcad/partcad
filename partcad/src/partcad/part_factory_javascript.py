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
            # The part's own choice outranks the package's, matching how
            # 'javascriptRequirements' works at both levels.
            javascript_version = config.get("javascriptVersion", None) or self.project.javascript_version
        self.runtime = self.ctx.get_javascript_runtime(javascript_version)
        # One session per part, not per package: a session carries the exact
        # dependency set its part asked for, and the environment it resolves to
        # is derived from that set (see runtime_javascript.env_dir_name). Two
        # parts of one package that want different Chili3D versions therefore
        # get different environments instead of overwriting each other's.
        self.session = self.runtime.get_session(source_project.name)

    def post_create(self) -> None:
        for dep in self.config.get("dependencies", []):
            self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
        # The sandbox is part of what produced the shape, so it belongs in the
        # cache key: a package that moves to another Node.js has to be rendered
        # again rather than served what the previous one built. Only the shape
        # config feeds the hash by default (see Shape.__init__), and these are
        # not in it - 'javascriptVersion' can come from the package rather than
        # the part, and the dependency set is resolved rather than declared.
        self.part.hash.add_string("nodejs:" + self.runtime.version)
        self.part.hash.add_dict({"javascriptRequirements": self.config.get("javascriptRequirements", [])})
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
