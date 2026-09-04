#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a PartCAD object type holds, as far as a client has to care: a mesh or not.

One question is asked here, and `partcad_client.external` is what asks it. Some
applications read triangles and nothing else -- Blender is the one PartCAD knows
about -- so handing one a STEP file is not a slow way of opening it, it is a file
the application cannot read at all. Such a file has to be turned into a mesh
first, and that is CAD work: it belongs to the daemon (`pc open` sends the same
`adhoc.convert` a `pc adhoc convert` does), while deciding *whether* it is needed
is a question about the type, which is what this module answers.

The tables are inlined copies of PartCAD's own, for the reason every other table
in a client is: `partcad_client` must stay cheap to import, and `import partcad`
costs seconds and a CAD kernel that a thin client may not even have. A copy that
can drift is only safe if something notices the drift, so
`tests/partcad_client/test_object_types.py` compares every table below against
the `partcad` one it mirrors and fails when a type is added there and not here.
That test is the reason these are tables and not a handful of `if`s.

"Mesh" means the file itself carries triangles -- what an STL, a 3MF, an OBJ, a
glTF or a three.js JSON is. Everything else is False, and False means exactly one
thing to a caller: *this is not already a mesh*, so an application that needs one
has to be given a converted copy. It is deliberately not a claim that the type
has no geometry -- `alias` and `enrich` are references, `extrude` and `sweep` are
built from a sketch, and none of them is a mesh; a mesh is what a conversion
produces out of any of them.
"""

import os
from typing import Dict, Optional, Tuple

__all__ = [
    "ASSY_EXTENSION",
    "EXTENSION_ALIASES",
    "PACKAGE_ONLY_TYPES",
    "PART_TYPE_EXTENSION",
    "PART_TYPE_IS_MESH",
    "SCENE_TYPE_EXTENSION",
    "is_mesh",
    "is_mesh_file",
    "is_mesh_type",
    "readable_scene_type",
    "readable_type",
    "scene_type_of_file",
    "type_of_file",
    "types_of_extension",
]

# Every part type PartCAD has, and whether what it names is already a mesh.
#
# The keys are the union of two sets, which is what the completeness test
# checks: the types registered as part factories (`partcad.globals`, which is
# what a package may declare) and the types the part extension mapping names
# (`partcad.shape.PART_EXTENSION_MAPPING`, which adds the ones PartCAD only ever
# writes -- there is no `threejs` factory, but `pc export -t threejs` produces
# one and `pc open` may well be handed the result).
#
# Adding a part type to PartCAD means adding it here. The test says so by name
# when it is forgotten, because the alternative is silent: a new mesh format
# would be converted to STL before Blender saw it, which works and is wrong.
PART_TYPE_IS_MESH: Dict[str, bool] = {
    # Meshes: triangles on disk, which a mesh application opens as they are.
    "stl": True,
    "3mf": True,
    "obj": True,
    "gltf": True,
    "threejs": True,
    # Boundary representations: surfaces and solids, not triangles.
    "step": False,
    "brep": False,
    "iges": False,
    # Scripts PartCAD runs to produce a shape. What comes out is a solid; the
    # file itself is source code, which no CAD application opens as geometry.
    "cadquery": False,
    "build123d": False,
    "chili3d": False,
    "sdf": False,
    "scad": False,
    # Shapes built by PartCAD out of something else in the package.
    "extrude": False,
    "sweep": False,
    "compound": False,
    # References to another object, which decide nothing themselves: whatever
    # they point at, a mesh application still gets there through a conversion.
    "alias": False,
    "enrich": False,
    # A part whose type is a package-defined 'partType' (see PartFactoryWrapper).
    # What the wrapper writes is not knowable from here, so it takes the same
    # route everything unknown does.
    "wrapper": False,
    # A KiCad part is the STEP file `kicad-cli` writes out of a board.
    "kicad": False,
    # An assembly description, not a shape: a URDF names the mesh files of its
    # links. It is in the part extension mapping, so it is answered here too.
    "urdf": False,
}

# The file extension each part type is stored in, inlined from
# `partcad.shape.PART_EXTENSION_MAPPING`. Only the types that are file formats
# are in it -- `alias`, `kicad` and the rest of the constructed types are not
# stored as anything.
PART_TYPE_EXTENSION: Dict[str, str] = {
    "step": "step",
    "brep": "brep",
    "stl": "stl",
    "3mf": "3mf",
    "threejs": "json",
    "obj": "obj",
    "iges": "iges",
    "gltf": "json",
    "urdf": "urdf",
    "cadquery": "py",
    "build123d": "py",
    "chili3d": "chili",
    "sdf": "py",
    "scad": "scad",
}

# Other spellings of the formats above. PartCAD names one extension per type,
# because that is what it writes; a file a user points `pc open` at was written
# by something else as often as not, and '.stp' and '.glb' are what that
# something else calls these.
EXTENSION_ALIASES: Dict[str, str] = {
    "stp": "step",
    "igs": "iges",
    "gltf": "gltf",
    "glb": "gltf",
}

# The extension of an ASSY file. 'assy' is an assembly type rather than a part
# type, so it is in neither table above -- but it is very much a file `pc open`
# is handed, and saying what it is beats reporting it as an unknown name.
ASSY_EXTENSION = "assy"

# The scene types that are file formats, and the extension each is stored in,
# inlined from `partcad.shape.SCENE_EXTENSION_MAPPING` (the same reason as every
# other table here, and the same completeness test).
#
# A second question from the one above, for a second kind of application. Blender
# reads triangles, so what `pc open` has to know about a file it is handed is
# whether the file holds any. MuJoCo reads a *scene description* and only its
# own -- so what has to be known there is which description format the file is,
# and that is what this answers.
#
# 'assy' is in it and is not convertible ad-hoc (see PACKAGE_ONLY_TYPES below):
# naming it is what lets the refusal say what the file is rather than report an
# unknown extension.
SCENE_TYPE_EXTENSION: Dict[str, str] = {
    "assy": "assy",
    "world": "world",
    "mjcf": "xml",
}

# Object types that only mean anything inside a package, inlined from
# `partcad.adhoc.adhoc.PACKAGE_ONLY_TYPES` (the same reason as every other table
# here, and the same completeness test). A conversion cannot be asked for one:
# there is no package around the file to resolve it against, so a caller has to
# say so rather than send a request that is refused.
PACKAGE_ONLY_TYPES: Dict[str, str] = {
    "urdf": "a URDF names the meshes of its links and becomes a part per link",
    "assy": "an ASSY file is a set of references to the parts of a package",
}


def _extension_types() -> Dict[str, Tuple[str, ...]]:
    """Every extension, and the types that are stored in it.

    More than one type can claim an extension -- '.py' is CadQuery, build123d
    and SDF alike -- so this maps to a tuple and the callers below say what they
    do about it. Nothing here guesses.
    """
    types: Dict[str, list] = {}
    for object_type, extension in PART_TYPE_EXTENSION.items():
        types.setdefault(extension, []).append(object_type)
    for extension, object_type in EXTENSION_ALIASES.items():
        if object_type not in types.setdefault(extension, []):
            types[extension].append(object_type)
    types.setdefault(ASSY_EXTENSION, []).append("assy")
    return {extension: tuple(sorted(names)) for extension, names in types.items()}


EXTENSION_TYPES: Dict[str, Tuple[str, ...]] = _extension_types()


def _extension_of(path: str) -> str:
    """The extension of ``path``, lowercased and without its dot."""
    return os.path.splitext(path)[1].lstrip(".").lower()


def types_of_extension(extension: str) -> Tuple[str, ...]:
    """The types stored in ``extension``, in a stable order; empty when unknown."""
    return EXTENSION_TYPES.get(extension.lstrip(".").lower(), ())


def type_of_file(path: str) -> Optional[str]:
    """The type of ``path``, when its name says so unambiguously.

    None when the extension is unknown, and None when more than one type shares
    it: a '.py' is a CadQuery script, a build123d script or an SDF one, and which
    it is is a fact about the package that declares it. A caller that needs the
    answer has to be told (`pc open --type`), because guessing wrong here means
    running the file as the wrong kind of script.
    """
    names = types_of_extension(_extension_of(path))
    return names[0] if len(names) == 1 else None


def readable_type(path: str, object_type: Optional[str] = None) -> Optional[str]:
    """The type a conversion should read ``path`` as, or None when nothing says.

    The declared type when it *is* a file format -- which is what a conversion
    needs, since reading the file means reading it as that format. Not every
    declared type is one: a `kicad` part is the STEP file `kicad-cli` wrote out
    of a board, an `alias` is a reference, and a part whose type names a
    package-defined `partType` (`//package:name`) is whatever that wrapper
    writes. Reading any of those *as their own type* would be reading the file
    as something it is not, so they fall through to the name, which describes
    the file that is actually there.

    A type this PartCAD has never heard of falls through the same way rather
    than being an error: `//package:name` is exactly that, and legitimate.
    """
    if object_type and object_type.lower() in PART_TYPE_EXTENSION:
        return object_type.lower()
    return type_of_file(path)


SCENE_EXTENSION_TYPES: Dict[str, str] = {
    extension: object_type for object_type, extension in SCENE_TYPE_EXTENSION.items()
}


def scene_type_of_file(path: str) -> Optional[str]:
    """The scene type ``path`` holds, judged by its name alone, or None.

    No extension is shared by two scene types, so unlike `type_of_file` this
    never has to decline to answer for ambiguity - only for an extension no
    scene type claims, which is most of them.
    """
    return SCENE_EXTENSION_TYPES.get(_extension_of(path))


def readable_scene_type(path: str, object_type: Optional[str] = None) -> Optional[str]:
    """The scene type a conversion should read ``path`` as, or None.

    The declared type when it is a scene format, and the file's own name
    otherwise - the same rule `readable_type` applies to parts, for the same
    reason: a declared type that is not a file format says nothing about how to
    read the file that is actually there.
    """
    if object_type and object_type.lower() in SCENE_TYPE_EXTENSION:
        return object_type.lower()
    return scene_type_of_file(path)


def is_mesh_type(object_type: Optional[str]) -> Optional[bool]:
    """Whether ``object_type`` is a mesh, or None when it is not a type we know."""
    if not object_type:
        return None
    return PART_TYPE_IS_MESH.get(object_type.lower())


def is_mesh_file(path: str) -> Optional[bool]:
    """Whether ``path`` holds a mesh, judged by its name alone.

    Answerable even where `type_of_file` is not: the three types stored in '.py'
    disagree about nothing that matters here, since none of them is a mesh. Only
    an extension no type claims -- or one whose types disagreed, which no
    PartCAD format does and a test keeps that way -- comes back as None.
    """
    answers = {is_mesh_type(name) for name in types_of_extension(_extension_of(path))}
    answers.discard(None)
    if len(answers) != 1:
        return None
    return answers.pop()


def is_mesh(path: str, object_type: Optional[str] = None) -> Optional[bool]:
    """Whether the object in ``path`` is a mesh, from its declared type and its name.

    A declared type settles it by saying *yes*: a part declared `stl` is an STL,
    whatever it is called. It does not settle it by saying no, because the types
    that are not mesh formats include the ones that name no file of their own --
    an `alias` is not a mesh, and neither is what it points at *as an alias*, but
    the file in hand may well be one. So a "no" defers to the name, and only a
    file whose extension no type claims comes back with the type's own answer.
    """
    answer = is_mesh_type(object_type)
    if answer:
        return True
    from_name = is_mesh_file(path)
    return answer if from_name is None else from_name
