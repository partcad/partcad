.. _cmf:

###
CMF
###

CMF is the colour, the material and the finish an item is made in. PartCAD keeps all three as **CMF declarations** of
the packages that use them, and an item names the ones it is made in. What CMF means for a design, and where an item's
comes from, is :doc:`/digital_thread/lifecycle/design_cmf`; this page is the configuration reference.

.. _cmf-declarations:

=================
CMF declarations
=================

A package declares colours under ``colors:``, materials under ``materials:`` and finishes under ``finishes:``. Each is
addressed as ``<package>:<name>`` -- or ``:<name>``, or just ``<name>``, for one of the package that writes the
reference -- and each kind has a namespace of its own, so a colour and a material may share a name.

All three take the same fields:

.. code-block:: yaml

  colors:            # or materials:, or finishes:
    <name>:
      desc: <(optional) what it is>
      url: <(optional) where to read about it>
      display: <(optional) how to draw it - a hint, see below>
      manufacturable: <(optional) false if this is only a picture; true by default>
      ids:           # (optional) what other systems call it
        <system>: <identifier>
      aliases: <(optional) other names of it in this package, one or a list>
      parameters:    # (optional) see "Parametric declarations"
        <name>: ...

**A display is a hint; a declaration is a claim.** ``display`` is only how to draw the thing. A declaration with
``manufacturable: true`` -- the default -- claims that what it declares can be sourced or made as declared, and that
claim is what :ref:`manufacturability <cmf-manufacturability>` counts. A colour that is only a picture says
``manufacturable: false``, and an item made in it is not manufacturable.

**Colours.** ``display`` is any CSS colour -- ``"#C91A09"``, ``"#C91A0980"``, ``"rgb(201 26 9)"``, ``"hsl(4 91% 41%)"``,
``"oklch(52% 0.19 33)"``, ``"color(display-p3 0.8 0.1 0.05)"``, ``"firebrick"`` -- or the reference of another colour,
whose display it takes. Every one is read as the sRGB colour CSS Colour Level 4 defines for it; a colour outside sRGB is
clipped. Quote a value that starts with ``#``: unquoted, YAML reads it as a comment. The short form is the display:

.. code-block:: yaml

  colors:
    signal-red:
      desc: Acme's signal red, as sold in the 2026 catalogue
      display: "#C91A09"
      ids: {acme: "SR-200"}
    accent: "#2F6FB0"          # the short form: a display and nothing else

**Materials** add the facts of a substance (see :ref:`materials`) and two of their own: ``display``, the look of the
substance as it comes, and ``color``, the colour declaration it claims for its natural surface. A part made of it that
states no colour is that colour, and counts as specified:

.. code-block:: yaml

  colors:
    natural-aluminium:
      display: "#A8A9AD"
  materials:
    al-6061-t6:
      full: Aluminium 6061-T6
      density: 2700
      color: :natural-aluminium

**Finishes** name a process and a surface specification through ``ids`` -- ``{vdi3400: "27"}``, ``{spi: "B-2"}``,
``{moldtech: "MT-11010"}`` -- and may give a 3D view two hints, from 0 to 1:

.. code-block:: yaml

  finishes:
    satin:
      desc: Satin, VDI 3400 Ref 27
      ids: {vdi3400: "27"}
      display: {roughness: 0.6, metallic: 0}
    anodised-black: Black anodised, MIL-A-8625 Type II, Class 2    # the short form: a description

A part that states no finish is **as produced**; nothing has to be declared for it.

.. _cmf-textures:

Textures
========

A colour may be drawn with an image instead of a plain colour: wood grain, a fabric, a brushed or printed surface. That
is its ``display`` in the long form, a mapping that names a PNG or a JPEG in the package:

.. code-block:: yaml

  colors:
    walnut:
      desc: Walnut veneer, as Acme supplies it
      ids: {acme: "WV-12"}
      display:
        image: textures/walnut.jpg   # a PNG or a JPEG, relative to this partcad.yaml
        size: 300                    # (optional) mm one copy of the image covers across; or [width, height]
        color: "#5C3A21"             # (optional) what it is drawn as where an image cannot be

A texture is how the colour is drawn, and nothing more: like any display it is a hint, and whether the colour is a
claim is still its ``manufacturable``. A part is drawn with it by naming the colour, as for any other:
``color: :walnut``. Another colour whose ``display`` names this one is drawn with the same image.

``size`` is how much of a surface one copy of the image covers, in millimetres: a number is its width, its height
following the image's proportions, and ``[width, height]`` sets both. Unset, an image covers 100 mm across. A surface
is covered with copies of the image side by side, laid on each face as on the side of a box around the part: seen from
the axis the face looks along most, upright (its top towards +Z, or towards +Y on a face looking up or down), not
mirrored, and starting from the part's origin. So a face keeps its texture wherever the part is placed, and two faces
meeting at an edge carry one image across it. A curved face shows a seam where it turns from one side of that box to
another.

``color`` is what the colour is drawn as wherever an image cannot be: the lines of a drawing, a swatch, ``pc list``.
Unset, it is the mean colour of the image. The image is drawn opaque; ``color`` with an alpha (``"#5C3A2180"``) makes
the textured surface see-through.

Where it is drawn:

* ``pc render`` of a PNG or a JPEG with ``style: shaded``, and every frame of a video, draw it.
* The IDE's *Digital Thread*, in its *Design > 3D* view, draws it; the CMF tab shows the image beside the colour.
* A drawing of lines -- SVG, DXF, and a PNG or a JPEG in the default ``style: lines`` -- draws the faces' edges in
  ``color``.
* ``pc export`` writes ``color`` where a file holds a colour (see :ref:`cmf-exports`); no export carries the image yet.

A one-sided shape -- a wall (see :ref:`walls`) -- in such a colour is laid with the image on its front, and is still
not there from behind.

The image is part of every part drawn with it: it travels inside the part's geometry, to the sandbox that renders it
and into the glTF the IDE is sent, so keep it to what a surface needs -- a few hundred kilobytes, a thousand or two
pixels a side. An image larger than 16 MB, outside the package, or neither a PNG nor a JPEG is reported against the
colour, which is then drawn in no colour at all.

Colour standards are not shipped with PartCAD. A package that works to one declares the colours it uses, the way a
vendor declares its own. The one colour PartCAD ships is ``//builtin/color:rgba``, below.

Aliases
=======

A declaration may be another name for one elsewhere -- in its own package or another -- which is how a package of
models gives a vendor's colours short names of its own:

.. code-block:: yaml

  colors:
    stone:
      type: alias
      source: "//pub/universe/lego:Medium Stone Grey"

``aliases:`` gives a declaration other names in its own package instead. Either way a reference through an alias is the
declaration it names: an item made in ``:stone`` is the same item as one made in
``//pub/universe/lego:Medium Stone Grey``.

Parametric declarations
=======================

A declaration may take parameters, which its fields name as ``%<parameter>%`` -- PartCAD's own expression syntax, since
``partcad.yaml`` is rendered as a Jinja2 template before any reference gives a value:

.. code-block:: yaml

  colors:
    rgba:
      parameters:
        color: {type: string, default: "DAA520FF"}
      display: "#%color%"
      manufacturable: false

``//builtin/color:rgba;color=C91A09FF`` is that declaration, shipped with PartCAD: the quick way to draw something in
a colour without claiming anything, and what PartCAD reads a hex or CSS colour as.

.. _cmf-names:

Names
=====

A CMF declaration is named as the specification it comes from names it -- ``Medium Stone Grey``,
``PA12, glass filled``, ``6061-T6 (SS)`` -- with no leading or trailing space. Inside a *reference*, the characters a
reference gives a meaning to are written percent-encoded:

==========  ========  ==========  ========
Character   Written   Character   Written
==========  ========  ==========  ========
``:``       ``%3A``   ``%``       ``%25``
``;``       ``%3B``   ``*``       ``%2A``
``,``       ``%2C``   ``?``       ``%3F``
``=``       ``%3D``   ``[``       ``%5B``
``#``       ``%23``   ``]``       ``%5D``
==========  ========  ==========  ========

So the colour declared as ``PA12, glass filled`` is referred to as ``:PA12%2C glass filled``. A name with a space is
quoted on a command line.

.. _cmf-parameters:

==============
CMF parameters
==============

Every part type and every assembly type accepts five parameters, whether or not its declaration mentions them:

``color``, ``material``, ``finish``
  A reference to a declaration of that kind. A colour that is no declaration but a colour (``"#C91A09"``, ``red``) is
  read as the display-only ``//builtin/color:rgba`` of it, with a warning.

``sourceCmf``
  What of the CMF the part's source -- its file, script or OpenSCAD model -- states is kept: ``keep`` (the default)
  keeps it all, and the parameters fill what it leaves unset; ``drop`` keeps none of it, and the parameters are all of
  the part's CMF; a list (``[color]``) keeps all but the components it names.

``cmfConvention``
  The converter that reads the source's CMF, when the source came from a tool other than the type's default.

.. code-block:: yaml

  parts:
    bracket:
      type: step
      path: bracket.step
      parameters:
        material: {type: string, default: //pub/std/manufacturing/material/metal:al-6061-t6}
        color: {type: string, default: ":anodised-black"}

    bracket-red:              # the same bracket, as an item of its own in another colour
      type: enrich
      source: :bracket
      with:
        color: ":signal-red"

A reference names a variant with them too -- ``:bracket;color=:signal-red`` -- and so does an ASSY link's ``params:``.
A variant is an item of its own, with its own line in the bill of materials.

An assembly's colour, material and finish are passed on to its links, each to a link whose ``params:`` do not set it
and whose item does not state it already: ``bracket-red`` linked into a black assembly stays red. A sub-assembly passes
them on in turn. CMF an assembly sets -- its own parameters, a link's ``params:`` -- draws the assembly; it does not
specify the items in it, and the assembly is then manufacturable only if it declares a ``vendor`` and an ``sku`` of its
own. A variant that is to be made or bought as such is declared as a part, as ``bracket-red`` is above, and linked by
name.

.. _cmf-sources:

What a part's source says
=========================

A part's source states CMF of its own, and the CMF parameters fill in what it leaves out (``sourceCmf`` says whether
they replace it instead):

``step`` and ``kicad``
  The colours a STEP file puts on its faces, solids and products, and the materials on its products, read through
  OpenCASCADE's XCAF reader. The geometry is what it was before.

``iges``
  The colours an IGES file puts on its entities, read through the IGES side of the same XCAF reader and in STEP's
  terms, which the package's ``cmfConvention`` converts as it does a STEP part's. A face sewn into a solid (see
  :ref:`cad-files`) keeps its colour; a solid the file states as one keeps the colour stated of it, and one sewn out
  of faces is in the colours of its faces.

The CAD applications' files (``fcstd``, ``f3d``, ``sldprt``, ``ipt``, ``catpart``, ``sat``, ``pvz``)
  What the STEP file cadmpeg converts each one to states, read the same way: for these part types and for the ``f3d``
  and ``pvz`` assemblies alike, in STEP's own terms, which the package's ``cmfConvention`` converts as it does a STEP
  part's. A FreeCAD document is read from the shapes in its archive where it can be, and those carry no colours --
  FreeCAD keeps them apart, in the document's view data, which is not read -- so only one read through its STEP file
  has any (see :ref:`cad-files`).

``build123d`` and ``cadquery``
  build123d's ``.color`` and ``.material`` on what a script shows and on the children of a compound; CadQuery's
  ``cq.Assembly`` colours and the ``color`` (and ``alpha``) option of ``show_object``. Every part script is also handed
  ``set_cmf`` beside ``show_object``, which states CMF in PartCAD's own terms, by reference, of the part, of one of its
  solids, or of one of its faces:

  .. code-block:: python

    from build123d import Box, Cylinder, Pos

    body = Box(10, 10, 10)
    peg = Pos(0, 0, 10) * Cylinder(2, 6)
    set_cmf(peg, color=":blue", material="//pub/std/manufacturing/material/plastic:pla")
    top = max(body.faces(), key=lambda face: face.center().Z)
    set_cmf(top, color=":signal-red")
    show_object([body, peg])

  What is said of a face wins over what is said of its solid, and what is said of a child over what is said of the
  compound holding it.

``scad``
  An OpenSCAD model's ``color()``, where the OpenSCAD in use writes colours into the 3MF it exports (the development
  snapshots since 2024 do; the 2021.01 release does not, and its parts are read as before). Each colour is an object of
  the 3MF, and the part is all of them.

``3mf`` and other meshes
  Each object of a 3MF in the display colour of its base material, and each triangle that names a base material of
  its own in that one's.

``gltf``
  Each face in the material of its triangle's primitive, as glTF states it, under the ``gltf`` convention: the
  material's name is the colour's, which a package claims with ``ids: {gltf: <name>}`` (one with no name is the colour
  it draws, as ``#RRGGBB``); its base colour -- glTF's linear factor, restated as sRGB -- is what the face is drawn in;
  and its roughness and metallic factors are the finish's display. Only what a material states is read: one drawn with
  a texture and no colour factor states no colour, and one that leaves out roughness or metallic does not have glTF's
  defaults stated for it. The material that covers most of a solid is the solid's, and the faces in another say
  theirs. A material PartCAD's own export wrote is read as the references it keeps under ``extras.partcad`` -- the
  colour, material and finish the part had, whatever ``cmfConvention`` says. Textures and vertex colours are not read.
  The parts of a ``gltf`` assembly, and of one ``pc import assembly`` makes of a glTF file, are read the same way.

  .. code-block:: yaml

    colors:
      signal-red:
        display: "#C91A09"
        ids:
          gltf: RedPaint          # a glTF material named 'RedPaint' is this colour

A package's own part type (``partTypes:`` of kind ``wrapper``)
  Its script may hand back, beside the shape, what each face (and solid) of it is in, as plain data in its own terms,
  for the convention it names to convert:

  .. code-block:: python

    output = {
        "shape": shape,
        "cmf": {
            "convention": "ldraw",
            "faces": [{"color": "4", "rgba": [201, 26, 9, 1.0]}, None, ...],
            "solids": [{"material": "abs"}, ...],
        },
    }

  One entry per face, in the order OpenCASCADE's ``TopExp::MapShapes`` visits them; ``None`` for a face it says
  nothing of. ``solids`` is the same for the solids, and is where a material is said: a solid is what is made of
  one, and a material said only of its faces leaves the solid's unspecified. A list that does not match the shape's
  faces (or solids) is dropped, and said to be.

``pc import`` of a STEP assembly keeps each part's colours and material in the part file it writes, and an instance's
own colour - an overriding style on one occurrence - becomes its link's ``params: {color: ..., sourceCmf: color}``.

.. _cmf-conventions:

Conventions
-----------

A source names colours, materials and finishes in its own terms, and they are converted into declarations as the part
is built. A name is looked up in the ``ids`` of the declarations of the part's own package, under the key of the
source's convention:

.. code-block:: yaml

  colors:
    signal-red:
      display: "#C91A09"
      ids:
        step: "#C91A09"           # a STEP file's faces of this colour are this one
        build123d: "#FF0000"      # and so is build123d's Color(1, 0, 0)
  materials:
    al-6061:
      ids:
        step: Aluminium 6061      # a STEP product made of 'Aluminium 6061'

The builtin conventions are ``partcad`` (references, as ``set_cmf`` writes them), ``step``, ``build123d``,
``cadquery``, ``openscad``, ``3mf``, ``gltf``, ``ldraw`` and ``usd`` (a USD material's name, see :ref:`the usd part type <usd-files>`);
each type uses its own, and a part's ``cmfConvention`` parameter names another. A colour nothing claims is drawn as the source drew it, as the display-only
``//builtin/color:rgba`` of its value; a material or a finish nothing claims is left for the parameters. Either is
reported once per part.

A package declares conventions of its own, each a variation on a builtin one:

.. code-block:: yaml

  cmfConventions:
    solidworks:
      extends: step              # reads what a STEP file states
      ids: solidworks            # looked up under 'ids: {solidworks: ...}'
      catalogs: [//pub/acme]     # and in these packages too, after the part's own
      caseFold: true

  parts:
    housing:
      type: step
      path: housing.step
      parameters:
        cmfConvention: {type: string, default: solidworks}

.. _cmf-exports:

What the exports write
======================

``pc export`` writes a part's CMF into every file type that has somewhere to put it, face by face:

``step``
  The product structure and names of what is exported -- a product per part and per assembly, a part placed twice
  one product placed twice -- through OpenCASCADE's XCAF writer. Each face's display colour, as sRGB, on the product,
  a solid or the face, whichever says it once; the material on the product where every solid of it is made of one,
  named by its reference, with what its declaration says it is and its density; and PartCAD's own references for
  every face and solid, as a user-defined attribute of the product (``partcad.cmf``). Read back as a ``step`` part,
  that attribute is what the part's CMF is read from -- the same colours, materials and finishes on every face and
  solid, by reference, whatever ``cmfConvention`` says -- for as long as the file still draws each face in the colour
  the attribute says. A file another tool has edited since is read by value, saying so.

``gltf``
  A material per set: named after its colour, material and finish, its display as glTF's (linear) base colour, its
  finish's roughness and metallic, and the references under the material's ``extras.partcad`` -- which is what a
  ``gltf`` part reads back (see :ref:`cmf-sources`).

``3mf``
  A base material per set, with its name and its display colour, named by the mesh object and by every triangle in
  another one. PartCAD's own mesh reader reads it back, triangle by triangle.

``urdf``
  A ``<visual>`` per set of a part whose faces are in several, each in its display colour; a part in one is one
  visual, as before.

``stl``, ``obj``, ``threejs``, ``iges`` and ``brep`` carry no CMF, and exporting a part that states any says, once per
file, that it is not in the file. ``mjcf`` is written by ``partcad/partcad-sim-mujoco``, which writes what it writes.

A face nobody coloured is written uncoloured, so that the reading tool draws it in its own default, rather than in the
goldenrod PartCAD draws it in. A face in a colour drawn with an image (see :ref:`cmf-textures`) is written in the colour
it is drawn as where an image cannot be: no export carries the image yet.

.. _cmf-check:

Checking it
===========

``pc test`` runs the ``cmf`` check on what a package says is to be made (``manufacturable: true``): every solid of a
part in a material and every face in a colour -- a material's colour claim counts -- each a declaration that claims it
can be had, and a finish that is one too where one is stated. It also reports an assembly that sets CMF and is not
bought whole. It warns, for now; an object or a package that says so fails instead:

.. code-block:: yaml

  cmf:
    require: true

``pc info`` of a part says what its CMF comes to: each set of colour, material and finish, how many faces and solids
are in it, which of its components are display-only, and what is left unspecified.
