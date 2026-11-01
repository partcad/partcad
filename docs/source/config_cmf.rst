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

``texture`` is reserved for a visual texture, in a later change. It is not a CMF component, and no declaration states
one.

Colour standards are not shipped with PartCAD. A package that works to one declares the colours it uses, the way a
vendor declares its own. The one colour the public index declares is ``//pub/std/color:rgba``, below.

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
        color: {type: string, default: "000000FF"}
      display: "#%color%"
      manufacturable: false

``//pub/std/color:rgba;color=C91A09FF`` is that declaration, in the public index: the quick way to draw something in a
colour without claiming anything.

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
  read as the display-only ``//pub/std/color:rgba`` of it, with a warning.

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

An assembly's CMF parameters are passed on to its links, for those a link's own ``params:`` do not set. CMF an
assembly sets -- its own parameters, a link's ``params:`` -- draws the assembly; it does not specify the items in it,
and the assembly is then manufacturable only if it declares a ``vendor`` and an ``sku`` of its own. A variant that is
to be made or bought as such is declared as a part, as ``bracket-red`` is above, and linked by name.
