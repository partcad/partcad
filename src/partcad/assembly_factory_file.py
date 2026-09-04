#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#


import hashlib
import os

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from . import telemetry
from .assembly_factory import AssemblyFactory
from . import logging as pc_logging


@telemetry.instrument()
class AssemblyFactoryFile(AssemblyFactory):
    # Where a rendered source file goes, under PartCAD's own state directory.
    # Not beside the original: rendering a template is derived data, and
    # instantiating an object must not drop files into the user's source tree.
    TEMPLATE_STATE_SUBDIR = "template"

    def __init__(self, ctx, source_project, target_project, config, extension=""):
        super().__init__(ctx, source_project, target_project, config)

        if "path" in config:
            self.path = config["path"]
        else:
            self.path = self.orig_name + extension

        if not os.path.isdir(source_project.config_dir):
            raise Exception(
                "ERROR: The project config directory must be a directory, found: '%s'" % source_project.config_dir
            )
        self.path = os.path.join(source_project.config_dir, self.path)

        if self.fileFactory is None:
            # If the user did not supply a way to download the file,
            # check if the file exists
            if not os.path.exists(self.path):
                raise Exception("ERROR: The %s path (%s) must exist" % (self.OBJECT_KIND, self.path))
        # Checked whether or not a download is configured, and so outside the
        # branch above: a path that exists but is a directory is a broken
        # configuration either way. When there is no file factory the path is
        # known to exist by now, so this still covers what devel checked there.
        if os.path.exists(self.path) and not os.path.isfile(self.path):
            raise Exception("ERROR: The %s path (%s) must be a file" % (self.OBJECT_KIND, self.path))

    def post_create(self) -> None:
        if self.path:
            self.assembly.path = self.path
            self.assembly.cache_dependencies.append(self.path)
        else:
            pc_logging.warning(f"The {self.OBJECT_KIND} path is not set: {self.assembly.name}")
        super().post_create()

    # -- Templating ---------------------------------------------------------
    #
    # Every text file an object is declared by is a Jinja2 template: an ASSY
    # file, a URDF, a Gazebo world and an MJCF model alike. That is what makes
    # one file describe a family of objects rather than one -- the built-in
    # scene '//builtin/scene:subject' is a template whose 'subject' parameter is
    # whatever is being simulated (see 'partcad.simulation') -- and it is why
    # the parameters reach the file under the same 'param_<name>' names in all
    # four formats.

    def template_params(self) -> dict:
        """The values this object's source file is rendered with.

        Every parameter as ``param_<name>``, plus ``name``. The configuration
        has been through '<Kind>Configuration.normalize()' by now, so every
        parameter is in the expanded form and carries the value to use: the
        declared default, overridden by '~/.partcad/config.yaml' or
        '--extra_param', overridden by the values given in the object name
        (e.g. '//package:assembly;length=96').
        """
        params = {}
        for param_name, param in (self.config.get("parameters") or {}).items():
            params["param_" + param_name] = param["default"]
        params["name"] = self.config["name"]
        return params

    def render_template(self, text: str) -> str:
        """Render one source file's text as a Jinja2 template.

        NOTE: the environment is sandboxed. The file comes from a package, which
        may well be somebody else's, and a plain Jinja environment lets a
        template reach through attribute access into the interpreter this runs
        in.
        NOTE: autoescape must stay off. The rendered document is YAML or XML,
        not HTML, so escaping corrupts every parameter value that contains '&',
        '<', '>', '"' or "'" (e.g. 'a & b' would reach the parser as
        'a &amp; b'). This matches how 'partcad.yaml' itself is rendered in
        'ProjectLocal'.
        """
        template = SandboxedEnvironment(
            loader=FileSystemLoader(os.path.dirname(self.path) + os.path.sep),
        ).from_string(text)
        return template.render(self.template_params())

    def rendered_source(self) -> str:
        """The path of this object's source file with its template rendered.

        The file itself when rendering changes nothing, which is the usual case
        and keeps a plain URDF exactly the file the package points at. Otherwise
        a copy under PartCAD's own state directory -- derived data belongs
        there rather than in the user's source tree -- whose name carries a
        digest of the source path and of the values it was rendered with, so
        two instances of one template do not overwrite each other and asking for
        the same instance twice reuses one file.

        Whatever the file references by a relative path is still resolved
        against the *original* file's directory: the readers are handed that
        directory separately, precisely because the file they parse may be this
        copy. A file that cannot be read is left to the reader to complain
        about, which is where every other unreadable-file message comes from.
        """
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            pc_logging.debug("%s: cannot read the source file to render it: %s" % (self.name, e))
            return self.path

        try:
            rendered = self.render_template(text)
        except Exception as e:  # pylint: disable=broad-except
            # A template that does not render is a broken declaration, and the
            # reader below would be handed the unrendered text and report
            # something unrelated. Say what actually went wrong.
            raise Exception("%s: failed to render the template %s: %s" % (self.name, self.path, e)) from e

        if rendered == text:
            return self.path

        digest = hashlib.sha256(("%s\0%s" % (os.path.abspath(self.path), rendered)).encode("utf-8")).hexdigest()[:16]
        directory = os.path.join(self.ctx.user_config.internal_state_dir, self.TEMPLATE_STATE_SUBDIR, digest)
        os.makedirs(directory, exist_ok=True)
        path = os.path.join(directory, os.path.basename(self.path))
        # Written every time rather than only when missing: the digest covers
        # the rendered text, so an existing file with this name holds exactly
        # this content, and rewriting it costs one small write while a stale
        # half-written file would cost a wrong answer.
        with open(path, "w", encoding="utf-8") as f:
            f.write(rendered)
        return path

    async def download_file_async(self, assembly) -> None:
        """Fetch what 'fileFrom' points at, unless the file is already there."""
        if self.fileFactory is not None and not os.path.exists(assembly.path):
            with pc_logging.Action("File", self.target_project.name, assembly.name):
                await self.fileFactory.download(assembly.path)

    async def prepare_async(self, assembly) -> None:
        """Download the source file without building the assembly.

        The cache key hashes the file's content, so it only means anything once
        the file is on disk. 'pc install' calls this for every object, which is
        why the first build after an install is a cache hit and not a miss.
        """
        await self.download_file_async(assembly)

    async def instantiate(self, assembly):
        await self.download_file_async(assembly)
