#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Common base for parts produced by a script running in a Node.js sandbox.

The JavaScript twin of part_factory_python: it resolves which Node.js sandbox
the part renders in and what goes into it, then hands the script to a wrapper
running there.

The dependency set is settled here, when the factory is constructed, rather than
when the part is rendered. Both the directory the part renders in and the cache
key its shape is stored under are derived from that set, so it must not still be
moving once a render starts.
"""

import os

from .part_factory_file import PartFactoryFile
from .runtime_javascript import JavaScriptRuntime, package_requirements, shape_requirements
from . import sandbox_versions
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

        # The package's declarations first, then the part's, so that the more
        # specific one replaces the other where they name the same npm package.
        # A subclass adds what its own part type needs after this returns.
        self.runtime.declare_requirements(self.session, package_requirements(self.project))
        self.runtime.declare_requirements(self.session, shape_requirements(config))

    def environment_cache_key(self) -> str | None:
        """The Node.js and the dependency versions this part renders with.

        The session's dependency set is exactly what gets installed, and is what
        the environment directory is named after, so there is nothing to resolve
        again here.
        """
        return sandbox_versions.environment_cache_key("nodejs", self.runtime.version, self.session["deps"])

    def post_create(self) -> None:
        for dep in self.config.get("dependencies", []):
            self.part.cache_dependencies.append(os.path.join(self.project.config_dir, dep))
        super().post_create()

    async def prepare_javascript(self):
        """
        This method is called by child classes
        to prepare the JavaScript environment
        before instantiating the part.

        Only provisioning: what to install was decided in the constructor.
        """
        await self.runtime.once_async()

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
