#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What an object's source file is to PartCAD: a file, a template, or bytes.

Every factory that builds an object out of one file -- named by 'path', or
fetched by 'fileFrom' -- is one of these, by class, through the file factory of
its kind ('PartFactoryFile', 'SketchFactoryFile', 'AssemblyFactoryFile'):

* 'SourceFile' -- handed to whatever reads it as it is. A STEP, an SVG, a DXF,
  a CadQuery script: PartCAD never opens the file itself, the wrapper does.
* 'TemplateSourceFile' -- text, rendered as a Jinja2 template with the object's
  parameters before anything reads it. An ASSY file, a URDF, a Gazebo world,
  MJCF: what lets one file describe a family of objects.
* 'BinarySourceFile' -- bytes. Never opened as text and never rendered: a 3MF
  archive, an STL, a DWG an 'import:' reader declared 'binary: true'.

Which one a file is is decided by its type and never by its content. A binary
file that happened to decode as UTF-8 is still not a template, and a template
that does not decode is a broken declaration, reported as one, rather than a
file to pass on untouched and hope.
"""

import hashlib
import os

from jinja2 import FileSystemLoader
from jinja2.sandbox import SandboxedEnvironment

from . import logging as pc_logging


class SourceFile:
    """A factory whose object is read from one file, which is handed over as it is.

    Where the file is and how it gets there are the same for every kind of
    object, so they are here once rather than in each kind's file factory:
    'locate_source()' resolves and checks 'path', and the download methods
    fetch what 'fileFrom' points at. Mixed in ahead of the kind's factory
    ('class PartFactoryFile(SourceFile, PartFactory)'), whose constructor sets
    'self.name', 'self.orig_name' and 'self.fileFactory' first.
    """

    #: The file is bytes, not text: nothing in PartCAD may open it as text.
    BINARY = False

    #: The file is a Jinja2 template, rendered before anything reads it.
    TEMPLATE = False

    #: What the object is called in an error about its file. An assembly
    #: factory says 'assembly' or 'scene' through its OBJECT_KIND instead.
    SOURCE_NOUN = "object"

    def locate_source(self, source_project, config, extension="", can_create=False) -> None:
        """Set 'self.path' to the object's file, and refuse one that cannot be it.

        'path' is relative to the package that declares the object, and defaults
        to the object's name with the type's extension. Without 'fileFrom' the
        file must exist, unless the type can create it ('can_create'); with or
        without, a path that exists and is not a file is a broken declaration.
        """
        noun = getattr(self, "OBJECT_KIND", None) or self.SOURCE_NOUN
        self.extension = extension

        if "path" in config:
            self.path = config["path"]
        else:
            self.path = self.orig_name + extension

        if not os.path.isdir(source_project.config_dir):
            raise Exception(
                "ERROR: The project config directory must be a directory, found: '%s'" % source_project.config_dir
            )
        self.path = os.path.join(source_project.config_dir, self.path)

        if self.fileFactory is None and not can_create and not os.path.exists(self.path):
            # If the user did not supply a way to download the file, it has to
            # be there already.
            raise Exception("ERROR: The %s path (%s) must exist" % (noun, self.path))
        # Checked whether or not a download is configured: a path that exists
        # but is a directory is a broken configuration either way.
        if os.path.exists(self.path) and not os.path.isfile(self.path):
            raise Exception("ERROR: The %s path (%s) must be a file" % (noun, self.path))

    def rendered_source(self) -> str:
        """The path of the file whatever reads this object is handed: here, the file itself."""
        return self.path

    async def download_file_async(self, shape) -> None:
        """Fetch what 'fileFrom' points at, unless the file is already there."""
        if self.fileFactory is not None and not os.path.exists(shape.path):
            with pc_logging.Action("File", self.target_project.name, shape.name):
                await self.fileFactory.download(shape.path)

    async def prepare_async(self, shape) -> None:
        """Download the source file without building the object.

        The cache key hashes the file's content, so it only means anything once
        the file is on disk. 'pc install' calls this for every object, which is
        why the first build after an install is a cache hit and not a miss.
        """
        await self.download_file_async(shape)

    async def instantiate(self, shape):
        await self.download_file_async(shape)


class BinarySourceFile(SourceFile):
    """A factory whose source file is bytes: the parent class of every binary format.

    It is a class rather than a guess so that what happens to a file is decided
    by its type: a file is never opened just to find out whether it would
    decode. Whatever reads the object is handed the file exactly as it is on
    disk.

    'rendered_source' is restated here rather than inherited because a binary
    variant of a templated factory ('AssemblyFactoryImportedBinary') reaches
    'TemplateSourceFile' through its other base, and must not render.
    """

    BINARY = True
    TEMPLATE = False

    def rendered_source(self) -> str:
        """The file itself: bytes are not a template."""
        return self.path


class TemplateSourceFile(SourceFile):
    """A factory whose source file is text and a Jinja2 template.

    Every text file an assembly or a scene is declared by is one: an ASSY file,
    a URDF, a Gazebo world and an MJCF model alike. That is what makes one file
    describe a family of objects rather than one -- the built-in scene
    '//builtin/scene:subject' is a template whose 'subject' parameter is
    whatever is being simulated (see 'partcad.simulation') -- and it is why the
    parameters reach the file under the same 'param_<name>' names in all four
    formats.

    Expects 'self.config' and 'self.ctx' besides what 'SourceFile' does.
    """

    TEMPLATE = True

    # Where a rendered source file goes, under PartCAD's own state directory.
    # Not beside the original: rendering a template is derived data, and
    # instantiating an object must not drop files into the user's source tree.
    TEMPLATE_STATE_SUBDIR = "template"

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

        A file that is not UTF-8 text is not a template, so it is an error here
        rather than something to hand over untouched: a format whose files are
        bytes is a 'BinarySourceFile' (an 'import:' reader says so with
        'binary: true'), and this is never reached for one.
        """
        try:
            # Text mode, for its newlines: a template written on Windows renders
            # to the same document as one written anywhere else.
            with open(self.path, "r", encoding="utf-8") as f:
                text = f.read()
        except OSError as e:
            pc_logging.debug("%s: cannot read the source file to render it: %s" % (self.name, e))
            return self.path
        except UnicodeDecodeError as e:
            raise Exception(
                "%s: %s is a template, and is not UTF-8 text (%s). A reader of a binary format declares "
                "'binary: true', and its files are handed over as they are" % (self.name, self.path, e)
            ) from e

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
