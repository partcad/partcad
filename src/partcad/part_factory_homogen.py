#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory import PartFactory


class PartFactoryHomogen(PartFactory):
    """The part types that produce a single homogeneous body.

    Mixed into a part factory to say that the part it produces is one solid
    made of one thing, and that the type therefore accepts the object-type
    parameters below (see 'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS').

    Homogeneity is the axis because it is what decides whether a single value
    can be true of the whole part - one material, one colour, one manufacturing
    tolerance. A mesh is one body: an STL file is a surface with nothing inside
    it to vary, and the only way it has a material at all is for somebody to
    say so. A solid a script builds is one
    body too - a CadQuery, build123d, SDF or OpenSCAD part is the result of one
    modelling session, and PartCAD hands the whole of it to a manufacturer as
    one thing. An extrusion of one sketch is the same case.

    'scad' arrived here later than the rest, and the case that brought it is
    worth keeping: '//pub/std/metric/bosl2' generates a part per BOSL2 module by
    parsing the module's signature, so a module argument called 'tolerance' -
    the fit clearance several of BOSL2's bottlecap adapters take - became a
    parameter of that name on a 'scad' part. The package was making no claim
    about manufacturing at all, and the whole public-index sweep went red on it.
    An OpenSCAD part was a homogeneous body the entire time; nothing but the
    opt-in was missing.

    A STEP file is not. It can carry many solids, so one tolerance for the
    file would be a claim about a part the file describes better than the
    declaration does. 'step' - and 'kicad', which is a STEP file behind a
    footprint and inherits this by inheriting 'PartFactoryStep' - therefore do
    not mix this in. They do take the CMF parameters, like every part type:
    what those state fills in what the file's own colours, materials and
    finishes leave out, or replaces them ('sourceCmf'; docs/design/cmf.md).

    Carries no '__init__' on purpose. It is mixed in ahead of a factory's real
    base ('PartFactoryStl(PartFactoryHomogen, PartFactoryFile)'), and a
    constructor here would sit in the middle of that diamond and have to
    forward every base's signature. With no constructor, attribute lookup walks
    straight past it to the real base, and all this class contributes is the
    class-level mapping below.
    """

    ACCEPTED_OBJECT_TYPE_PARAMETERS = {
        # The CMF parameters, which every part type accepts (see
        # 'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS').
        **PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS,
        # A default of 0.0, meaning "nobody said". It is a real value rather
        # than a sentinel because the manufacturability tests need something to
        # compare against, and because 0.0 - a demand for perfect precision -
        # is exactly what an unspecified manufacturing tolerance amounts to.
        # Being numeric is also what tells the reader to hand it back as a
        # number (see 'ShapeConfiguration.get_object_type_parameter'). The
        # default is applied on read and never written into
        # 'config["parameters"]', so a part that declares no tolerance keeps
        # the cache key it has always had.
        "tolerance": 0.0,
    }
