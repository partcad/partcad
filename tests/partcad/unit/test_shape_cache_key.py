#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What of a shape's configuration reaches its cache key.

The key has to cover everything that decides the geometry. It used to cover an
allow-list of 'parameters', 'offset' and 'scale', which cannot be complete: a
partType of kind 'wrapper' is a package-supplied script reading configuration
keys of its own invention, and the ':ldraw' partType identifies its part with
'dat'. Every LDraw part therefore hashed to one key, and whichever was meshed
first was served for all of them - four different parts exported byte-identical
geometry.

So the rule is inverted here: everything is hashed except the keys that only
describe the shape to a reader.
"""

from partcad.shape import Shape


def _key(config):
    shape = Shape("pkg", config)
    shape.set_environment_cache_key("env")
    return shape.hash.get()


def test_a_wrapper_part_type_key_separates_parts_it_alone_understands():
    """The regression: 'dat' is what says which LDraw part this is."""
    brick = _key({"name": "part", "type": ":ldraw", "dat": "3001.dat"})
    other = _key({"name": "part", "type": ":ldraw", "dat": "3003.dat"})
    assert brick != other


def test_prose_about_a_shape_does_not_move_its_key():
    """A description is not geometry; rewording one must not force a rebuild."""
    bare = _key({"name": "part", "type": ":ldraw", "dat": "3001.dat"})
    described = _key(
        {
            "name": "part",
            "type": ":ldraw",
            "dat": "3001.dat",
            "desc": "Brick  2 x  4",
            "author": "James Jessiman",
            "license": "CC BY 4.0",
            "url": "https://library.ldraw.org/",
        }
    )
    assert bare == described


def test_a_key_the_hash_has_never_heard_of_is_still_hashed():
    """An unknown key is assumed to matter.

    The two mistakes are not symmetrical. Hashing a key that turns out not to
    matter costs a rebuild; missing one that does matter serves the wrong shape
    and says nothing.
    """
    without = _key({"name": "part", "type": "step", "path": "a.step"})
    with_it = _key({"name": "part", "type": "step", "path": "a.step", "someFutureKey": 7})
    assert without != with_it


def test_the_geometry_keys_that_were_always_hashed_still_are():
    base = {"name": "part", "type": "step", "path": "a.step"}
    assert _key(base) != _key({**base, "parameters": {"n": {"type": "int", "default": 1}}})
    assert _key(base) != _key({**base, "offset": [[1, 0, 0], [0, 0, 1], 0]})
    assert _key(base) != _key({**base, "scale": 2.0})


def test_the_file_a_part_is_built_from_reaches_the_key():
    assert _key({"name": "part", "type": "step", "path": "a.step"}) != _key(
        {"name": "part", "type": "step", "path": "b.step"}
    )


def test_what_a_shape_is_called_is_not_what_it_is_made_of():
    """Two parts alike but for their names are one shape, and share an entry.

    A file-backed part reaches its key through the file's content, so the name
    it happens to carry - and the 'orig_name' the factory records beside it -
    are not part of what is being cached.
    """
    assert _key({"name": "a", "orig_name": "a", "type": "step", "path": "body.step"}) == _key(
        {"name": "b", "orig_name": "b", "type": "step", "path": "body.step"}
    )


def test_properties_are_outputs_and_do_not_move_the_key():
    """A part that gains a material has not become a different shape."""
    base = {"name": "part", "type": "step", "path": "a.step"}
    assert _key(base) == _key({**base, "properties": {"material": "steel"}})
