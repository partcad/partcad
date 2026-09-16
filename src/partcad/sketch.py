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

    # What this drawing says beside the geometry, as two cache entries filled in
    # as the sketch is built (see 'Shape.CACHED_SIDE_DATA' for how they survive
    # the cache, and 'wrappers/dxf_metadata.py' for what each holds): what it
    # says about its own elements, and what it says about itself.
    CACHED_SIDE_DATA = {"annotations": "annotations", "metadata": "file_metadata"}

    def __init__(self, project_name: str, config: dict = {}) -> None:
        super().__init__(project_name, config)

        self.kind = "sketch"
        self.annotations = []
        self.file_metadata = {}

    async def get_shape(self, ctx):
        return await threadpool_manager.run_async(self.instantiate, self)

    async def get_annotations(self, ctx) -> list:
        """What this sketch says about its own elements, one record per element.

        The internal representation of a sketch is BREP, which has nowhere to
        put an angle written against a line, so whatever the source stated about
        its elements is carried beside the geometry instead. A DXF states it as
        XDATA and 'wrappers/dxf_metadata.py' reads it; a sketch of any other
        type has nothing to say yet and answers with an empty list.

        That is the whole point of it being a property of the *sketch*: the
        sheet metal instructions are a sketch, not a DXF file, and the day
        another sketch type learns to state the same thing, nothing that reads
        this has to change.

        Building the sketch is what fills it in, so this asks for the shape -
        which is a cache hit for a sketch that has been built before, because
        the annotations are cached beside the geometry and come back with it.
        """
        await self.get_wrapped(ctx)
        return self.annotations or []

    async def get_file_metadata(self, ctx) -> dict:
        """What the file this sketch was read from says about itself.

        The layers it declares, the application that wrote it, what its numbers
        are in - see 'wrappers/dxf_metadata.describe'. Carried the same way, and
        for the same reason, as the annotations beside it: none of it survives
        the trip into BREP, and a sketch that came out of the cache was never
        instantiated to be asked.

        It is about the *file* rather than about the sketch, which is what makes
        it worth carrying separately: a sketch is the layers its filters
        selected, and the interesting thing about the ones they did not select
        is that they exist. A sketch type that reads no file - and every type
        but 'dxf' today - answers with an empty mapping.
        """
        await self.get_wrapped(ctx)
        return self.file_metadata or {}
