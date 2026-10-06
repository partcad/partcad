#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import asyncio

from partcad import thumbnail

SVG = (
    "<?xml version='1.0' encoding='utf-8'?>\n"
    '<svg width="448.1mm" height="513.0mm" viewBox="-7 -8 14 16" version="1.1" '
    'xmlns="http://www.w3.org/2000/svg">\n<g/>\n</svg>\n'
)


def test_a_thumbnail_says_how_many_pixels_it_is_drawn_at():
    sized = thumbnail.sized(SVG, 64, 48)

    assert '<svg width="64" height="48" preserveAspectRatio="xMidYMid meet"' in sized
    assert 'viewBox="-7 -8 14 16"' in sized
    assert "mm" not in sized


def test_the_size_is_part_of_the_cache_key():
    assert thumbnail.cache_key(64, 64) != thumbnail.cache_key(128, 128)
    assert thumbnail.cache_key(64, 48) != thumbnail.cache_key(48, 64)


class _Hash:
    def get(self):
        return "abc"


class _Cache:
    def __init__(self):
        self.entries = {}
        self.writes = 0

    async def read_data_async(self, hash, keys):
        return {key: self.entries.get((hash.get(), key)) for key in keys}

    async def write_data_async(self, hash, items):
        self.writes += 1
        for key, value in items.items():
            self.entries[(hash.get(), key)] = value
        return {key: True for key in items}


class _Shape:
    project_name = "//pkg"
    name = "bracket"

    def __init__(self):
        self.hash = _Hash()
        self.renders = []

    async def get_wrapped(self, ctx):
        return {"shape": True}

    def get_cacheable(self):
        return True

    async def render_async(self, ctx, format_name, filepath=None, **kwargs):
        self.renders.append(kwargs)
        with open(filepath, "w") as f:
            f.write(SVG)


class _Context:
    def __init__(self):
        self.cache_renders = _Cache()


def test_a_thumbnail_is_drawn_once_per_shape_and_size():
    ctx, shape = _Context(), _Shape()

    first = asyncio.run(thumbnail.svg_thumbnail_async(ctx, shape, 64, 64))
    again = asyncio.run(thumbnail.svg_thumbnail_async(ctx, shape, 64, 64))
    bigger = asyncio.run(thumbnail.svg_thumbnail_async(ctx, shape, 128, 128))

    assert first == again
    assert b'width="64"' in first and b'width="128"' in bigger
    assert len(shape.renders) == 2
    # Lines are drawn wider for a smaller picture, so that they come out the
    # same width on screen.
    assert shape.renders[0]["line_weight"] == 2 * shape.renders[1]["line_weight"]
