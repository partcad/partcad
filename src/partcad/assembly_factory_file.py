#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-26
#
# Licensed under Apache License, Version 2.0.
#


from . import logging as pc_logging
from . import telemetry
from .assembly_factory import AssemblyFactory
from .file_source import TemplateSourceFile


@telemetry.instrument()
class AssemblyFactoryFile(TemplateSourceFile, AssemblyFactory):
    """An assembly or a scene read from one file, which is a Jinja2 template.

    See 'TemplateSourceFile' for the rendering, and 'BinarySourceFile' for the
    formats that are bytes instead ('AssemblyFactoryImportedBinary').
    """

    def __init__(self, ctx, source_project, target_project, config, extension=""):
        super().__init__(ctx, source_project, target_project, config)
        self.locate_source(source_project, config, extension=extension)

    def post_create(self) -> None:
        if self.path:
            self.assembly.path = self.path
            self.assembly.cache_dependencies.append(self.path)
        else:
            pc_logging.warning(f"The {self.OBJECT_KIND} path is not set: {self.assembly.name}")
        # The source file with its template rendered, for a caller that has to
        # read the document PartCAD reads rather than the text somebody wrote:
        # 'pc filter' rewrites that document, and a templated file is not YAML
        # until it has been rendered. The object keeps no other handle on its
        # factory, and the parameter values a template is rendered with are the
        # factory's (see 'template_params').
        self.assembly.rendered_source = lambda: self.rendered_source()
        super().post_create()
