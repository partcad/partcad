#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The sketch a part is swept from, as 'sweep' and 'routed' resolve it (design D6
of issue #975).

Both name a sketch in their declaration, both key the part on what that sketch
contains, and both hand it to their wrapper as a BREP envelope. That much is the
same code; what the sketch is swept along is each factory's own.
"""

from . import logging as pc_logging


class SketchProfile:
    """Mixed into a part factory that is made from a named sketch.

    'resolve_sketch' reads which sketch, in the constructor. 'prepare_async' folds
    the sketch's own cache key into the part's, and 'sketch_envelope' fetches the
    sketch as the BREP envelope a wrapper takes.
    """

    source_project_name: str
    source_sketch_name: str
    source_sketch_spec: str

    def resolve_sketch(self, source_project, config, default="sketch") -> str:
        """Which sketch the declaration names, as '<package>:<sketch>'.

        A name with a ':' is resolved against the declaring package; a 'project:'
        field names the package outright ('this' or empty for the declaring one).
        """
        self.source_sketch_name = config.get("sketch", default)
        if "project" in config:
            self.source_project_name = config["project"]
            if self.source_project_name == "this" or self.source_project_name == "":
                self.source_project_name = source_project.name
        else:
            if ":" in self.source_sketch_name:
                self.source_project_name, self.source_sketch_name = source_project.resolve(
                    self.source_sketch_name,
                )
            else:
                self.source_project_name = source_project.name
        self.source_sketch_spec = self.source_project_name + ":" + self.source_sketch_name
        return self.source_sketch_spec

    async def prepare_async(self, part) -> None:
        """Resolve the sketch, and key this part on what it contains too.

        The name of the sketch is in the key already; its content is not, and
        without it an edited sketch goes on being swept from the entry
        the old one produced.
        """
        sketch = self.ctx.get_sketch(self.source_sketch_spec, referrer=self.project.name)
        if sketch is None:
            # Reported by 'instantiate', which is where it always was.
            return
        if await part.add_cache_key_of(sketch):
            part.cache_dependencies_broken = False
        else:
            # A sketch with no key - 'cache: false' - has content nothing here
            # can vouch for, so neither has what is built out of it.
            part.cacheable = False

    async def sketch_envelope(self, part):
        """The sketch as the BREP envelope a wrapper takes, or None, reported on
        the part, when it produced no shape."""
        self.sketch = self.project.ctx.get_sketch(self.source_sketch_spec, referrer=self.project.name)
        if self.sketch is None:
            part.error("%s: %s: sketch not found: %s" % (part.project_name, part.name, self.source_sketch_spec))
            return None
        sketch_env = await self.sketch.get_wrapped(self.ctx)
        if sketch_env is None:
            part.error("%s: %s: the source sketch produced no shape" % (part.project_name, part.name))
            return None
        pc_logging.debug("%s: %s: swept from %s" % (part.project_name, part.name, self.source_sketch_spec))
        return sketch_env
