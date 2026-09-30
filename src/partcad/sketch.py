#
# OpenVMP, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-04-20
#
# Licensed under Apache License, Version 2.0.
#

import typing

from .shape import Shape
from .sync_threads import threadpool_manager


class Sketch(Shape):
    path: typing.Optional[str] = None

    def __init__(self, project_name: str, config: dict = {}) -> None:
        super().__init__(project_name, config)

        self.kind = "sketch"

    async def get_shape(self, ctx):
        return await threadpool_manager.run_async(self.instantiate, self)

    async def get_annotations(self, ctx) -> list:
        """What this sketch says about its own elements, one record per element.

        The internal representation of a sketch is BREP, which has nowhere to
        put an angle written against a line, so whatever the source stated about
        its elements is carried beside the geometry instead - in the envelope's
        metadata, which is where everything a wrapper records about a shape
        travels and is cached (see 'shape_envelope.METADATA_ANNOTATIONS'). A DXF
        states it as XDATA and 'wrappers/dxf_metadata.py' reads it; a sketch of
        any other type has nothing to say yet and answers with an empty list.

        That is the whole point of it being a property of the *sketch*: the
        sheet metal instructions are a sketch, not a DXF file, and the day
        another sketch type learns to state the same thing, nothing that reads
        this has to change.

        Kept as a method of its own, rather than left to the generic accessor it
        now forwards to, because this is the name the manufacturing checks ask
        by and the question really is about a sketch.
        """
        return await self.get_annotations_async(ctx)
