#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .part_factory import PartFactory


class PartFactoryHomogen(PartFactory):
    """The part types that produce a single homogeneous body.

    Mixed into a part factory to say that the part it produces is one solid
    made of one thing, and that the type therefore accepts 'material' as an
    object-type parameter (see 'PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS').

    Homogeneity is the axis because it is what decides whether a single
    'material:' value can be true of the whole part. A mesh is one body: an STL
    file is a surface with nothing inside it to vary, and the only way it has a
    material at all is for somebody to say so. A solid a script builds is one
    body too - a CadQuery, build123d or SDF part is the result of one modelling
    session, and PartCAD hands the whole of it to a manufacturer as one thing.
    An extrusion of one sketch is the same case.

    A STEP file is not. It can carry many solids, each with a material of its
    own already stated in the file, so naming one material for the file would
    be a claim about a part the file describes better than the declaration
    does. 'step' - and 'kicad', which is a STEP file behind a footprint and
    inherits this by inheriting 'PartFactoryStep' - therefore do not mix this
    in. What such a part is made of belongs in 'properties:', which is where a
    shape says what it turned out to be rather than what was asked of it.

    Carries no '__init__' on purpose. It is mixed in ahead of a factory's real
    base ('PartFactoryStl(PartFactoryHomogen, PartFactoryFile)'), and a
    constructor here would sit in the middle of that diamond and have to
    forward every base's signature. With no constructor, attribute lookup walks
    straight past it to the real base, and all this class contributes is the
    class-level set below.
    """

    ACCEPTED_OBJECT_TYPE_PARAMETERS = PartFactory.ACCEPTED_OBJECT_TYPE_PARAMETERS | {"material"}
