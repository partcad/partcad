CMF
###

Colour, material and finish -- CMF -- are part of what an item *is*. A red housing and a black housing are two items,
ordered, stocked and inspected apart; LEGO sells an *element*, a design in a colour. So in PartCAD the CMF of an item is
stated by the item's own definition, carried with its geometry, checked before it is made, and shown the same way
wherever the item is.

Declarations, and claims
========================

A colour, a material or a finish is a **CMF declaration** of the package that uses it (see :ref:`cmf`): a name, what
other systems call it, and how to draw it. Two things are kept apart:

- **the claim** -- a declaration with ``manufacturable: true``, the default, says that what it declares can be sourced
  or made as declared;
- **the display** -- a colour to draw it in, which says nothing about what can be had. A colour that is only a picture,
  such as ``//builtin/color:rgba;color=C91A09FF``, declares ``manufacturable: false``.

A finish names a process and a surface specification (a VDI 3400 reference, an SPI grade, an anodising type); a part
that states none is as produced. A material may claim the colour of its natural surface, so an unpainted aluminium part
is specified by its material.

Where an item's CMF comes from
==============================

From its definition, and nothing else:

1. what its **source** states -- a STEP file's colours and materials, a script's, an OpenSCAD model's -- read through
   the converter for the tool it came from (``cmfConvention``; see :ref:`cmf-sources`);
2. its **CMF parameters** -- ``color``, ``material`` and ``finish`` -- which fill what the source leaves unset, or, with
   ``sourceCmf``, replace it;
3. for its colour, its **material's** claim.

Inside a part, the more specific wins: a face's own colour over its solid's, a solid's over the part's. A face nothing
colours is drawn in goldenrod, the colour OCCT draws what nobody coloured.

A part in another colour is **another item**: ``bracket;color=:signal-red``, or an ``enrich`` that fixes ``color``, has
its own line in the bill of materials and its own question to a supplier.

.. _cmf-manufacturability:

What manufacturing asks of it
=============================

A part that is to be made has to have every solid in a material and every face in a colour, each a declaration that
claims it can be had. A display-only colour does not; neither does a face nothing coloured.

An assembly may set CMF for what it holds -- its own CMF parameters are passed on to the links whose items state none,
and a link's ``params:`` choose a variant -- but that draws the assembly; it does not specify the items in it. An
assembly that sets CMF is manufacturable only if it is bought whole, declaring a ``vendor`` and an ``sku`` of its own. A
variant that is to be made or bought as such is declared as a part, and the assembly links it by name. An assembly
bought whole is judged by its own CMF: how its vendor put it together, and what the parts inside it are made of, are its
vendor's to say.

``pc test`` asks all of this of everything to be made, in its ``cmf`` check (see :ref:`cmf-check`). It warns for now,
and fails what says ``cmf: require: true``.

Seeing it
=========

``pc list colors``, ``pc list materials`` and ``pc list finishes`` list a package's declarations alike: name, display,
whether it is only a picture, and what it is. ``pc info`` of a part says what its CMF comes to.

A part's CMF travels with its geometry, inside its BREP, so whatever draws the part draws it in its colours: the SVG,
PNG and JPEG drawings colour each face as its CMF says, and the glTF a part is shown with carries a material per
colour.
