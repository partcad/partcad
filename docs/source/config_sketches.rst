.. _sketches:

########
Sketches
########


PartCAD uses 2D sketches to create 3D models (e.g. via `extrude` or `sweep`) and to maintain
various metadata (such as the geometry of interfaces between parts,
arbitrary part metadata like camera view angles and so on).

- Basic shapes

  - Outer shape: `circle`, `rectangle`, `square`, `slot`
  - Optional inner shape: `circle`, `rectangle`, `square`, `slot`

- Files

  - DXF
  - SVG

- Scripts

  - `build123d <https://github.com/gumyr/build123d>`_
  - `CadQuery <https://github.com/CadQuery/cadquery>`_


Sketches are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: <basic|dxf|svg|cadquery|build123d>
      desc: <(optional) textual description>
      path: <(optional) the source file path, "{sketch name}.{ext}" otherwise>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      # ... type-specific options ...

Basic
=====

The basic sketches are defined using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: basic
      desc: <(optional) textual description>
      # The below are mutually exclusive options
      circle: <(optional) radius>
      circle:  # alternative syntax
        radius: <radius>
        x: <(optional) x offset>
        y: <(optional) y offset>
      square: <(optional) edge size>
      square:  # alternative syntax
        side: <edge size>
        x: <(optional) x offset>
        y: <(optional) y offset>
      rectangle: <(optional)>
        side-x: <x edge size>
        side-y: <y edge size>
        x: <(optional) x offset>
        y: <(optional) y offset>
      slot: <(optional)>
        length: <overall length, measured over the rounded ends>
        width: <width, which is the diameter of those ends>
        x: <(optional) x of the centre of the first rounded end>
        y: <(optional) y of the centre of the first rounded end>
        angle: <(optional) degrees to turn it about that point, 0 = along X>
      inner: <(optional) the shapes cut out of the one above>
        circle: <(optional) radius>
           ...
        square: <(optional) edge size>
           ...
        rectangle: <(optional)>
           ...
        slot: <(optional)>
           ...
        circles: <(optional) several of them at once>
          - ...
        squares: ...
        rectangles: ...
        slots: ...

There must be only one field ``circle``, ``square``, ``rectangle`` or ``slot`` at the top level of the sketch.
Inside ``inner`` each shape may be given once by its own name, and several at a time in the plural list beside it.

A **slot** is a rectangle with semicircular ends -- two arcs and two lines --
which is what a slotted hole is. ``length`` is measured over those ends, the way
a drawing dimensions it, so a slot as long as it is wide is a circle rather than
an error.

Unlike the other shapes, a slot is placed by the centre of its **first** rounded
end rather than by its middle, and ``angle`` turns it about that point. That is
where a slot comes from: it is a hole that may also sit somewhere else, so it
starts where the plain hole would have been and runs ``length - width`` from
there. A port keeps its coordinates when the opening it marks is slotted, and
the freedom of movement that goes with it runs from zero rather than from half a
slot back. It is also the only one of these shapes whose direction is part of
what it is.

.. code-block:: yaml

  sketches:
    m4-slotted-30:
      desc: The boundary of an M4 hole that may sit anywhere in the next 26mm
      type: basic
      slot: { length: 30.0, width: 4.0 }

DXF
===

A sketch can be defined using a `DXF <https://en.wikipedia.org/wiki/AutoCAD_DXF>`_ file.
Such sketches are declared using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: dxf
      desc: <(optional) textual description>
      path: <(optional) filename> # otherwise "<sketch-name>.dxf"
      tolerance: <(optional) tolerance used for merging edges into wires>
      include: <(optional) a layer name or a list of layer names to import>
      exclude: <(optional) a layer name or a list of layer names not to import>
      units: <(optional) what the numbers are in: auto (default), unitless, mm, in, ...>

The sketch is **every face** the selected layers draw. Each layer's lines, arcs,
circles, ellipses, splines and polylines are joined end to end into outlines;
each closed outline becomes a face, with the outlines inside it as its holes. A
drawing of several outlines -- side by side, or one on each of several layers
-- is a sketch of several faces. A line that does not close bounds nothing, and
is kept as the **wire** it is, beside the faces: an outline and the bend lines
across it are a sketch of one face and two lines. Text, dimensions and hatches
are not geometry and are left out of it.

**Block references** (``INSERT``, and the grids ``MINSERT`` places) draw what
the block draws, where the reference puts it: moved, turned, scaled and mirrored
as placed, with blocks inside blocks followed all the way down. An entity a block
keeps on layer ``0`` is on the reference's layer, which is what layer ``0`` in a
block means; an entity on any other layer stays on that layer wherever the block
is placed, and the layer filters below select it there.

A **mirrored** arc, circle or polyline -- what ``MIRROR`` writes, and what a
block reference with a negative scale places -- is read where it was mirrored
to.

The sketch is in **millimetres**, whatever the drawing is drawn in: its numbers
are scaled by what ``$INSUNITS`` says they are, so a one-inch profile drawn in
inches is a 25.4 mm sketch. A drawing that says it is unitless is taken as
millimetres. ``units:`` says what the numbers are where the drawing does not, or
says wrong -- ezdxf, for one, saves a drawing as metres unless it is told
otherwise -- and ``unitless`` takes them as millimetres as they are. ``pc info``
reports both what the drawing says and how much the sketch was scaled by (see
:ref:`sketch-annotations`). PartCAD's own DXF output says it is in millimetres.

.. _sketch-layers:

Layers, and reading one drawing several ways
--------------------------------------------

``include`` and ``exclude`` are **object-type parameters**: the ``dxf`` type
contributes them rather than the author of the sketch inventing them, in the
same way ``material``, ``color`` and ``tolerance`` are contributed to a part (see
:ref:`parameters`). Two things follow from that, and both are the point of it.

First, they exist whether or not the declaration mentions them, so whoever
*refers* to the sketch can set them -- and a reference is the natural place for
this to be decided, because which layers are wanted depends on what the sketch is
being used for:

.. code-block:: yaml

  sketches:
    panel:
      type: dxf       # one drawing: the outline, the bend lines, the notes

  parts:
    sheet:
      type: step                        # the stock the blank is cut out of

    blank:
      type: extrude
      sketch: panel;include=OUTLINE     # the flat pattern
      depth: 2.0
      manufacturing:
        method: subtractive
        source: sheet

    bracket:
      type: step
      manufacturing:
        method: sheet_metal
        source: blank
        instructions: panel;include=BEND_UP,BEND_DOWN   # the bends, from the same drawing

A list is written with commas in it, as above. Nothing has to be declared in
advance for either reference to work, and each of them is its own sketch --
with its own cache entry -- so the two do not have to be rendered twice or kept
in step by hand.

Layer names are matched **case-insensitively**, and only one of ``include`` and
``exclude`` may be given -- both are the DXF importer's own rules. A reference
setting either of them is deciding how the drawing is read, so it replaces what
the declaration said rather than being added to it: a sketch declaring
``include: [OUTLINE]`` and referred to as ``panel;exclude=NOTES`` is read by
that exclusion alone. A reference that sets *both* is refused, the way a
declaration writing both is.

What the selected layers draw that does not close is imported as the **wires**
it is, beside the faces the rest bound. That is what a drawing of bend lines is:
two parallel lines across a blank are where it is folded, and a line is open by
nature. PartCAD says so when it happens, because the other way to arrive there
is an outline with a gap in it, which is a mistake rather than a drawing of
lines.

Second, the fields above are the **default** the reference overrides. They go on
meaning exactly what they always meant, and a sketch that carries neither reads
every layer. The long form is available too, for a sketch that wants to describe
its own default:

.. code-block:: yaml

  sketches:
    panel:
      type: dxf
      parameters:
        include:
          desc: The layers this drawing is read from
          type: array
          default: [OUTLINE]

Every other sketch type rejects the two names, the way a part type rejects an
object-type parameter it cannot honour: a layer is something a DXF has, and
accepting the parameter silently on an SVG would leave a package believing it was
filtering something.

.. _sketch-annotations:

Annotations
-----------

A DXF entity may carry **extended data** -- XDATA -- which is what an application
wrote against that entity, in the file, beside the geometry. It is where a
drawing states what the geometry cannot: two identical lines are a bend up
through 90 degrees and a bend down through 30, and nothing about the lines says
which.

PartCAD reads it as the file is imported and carries it beside the geometry from
then on, so it is a property of the **sketch** rather than of the file it came
from. That is what lets :ref:`sheet metal instructions <sheet-metal>` be a
sketch: the check reads what the sketch reports, and a sketch type that learns to
state the same thing needs no change anywhere else. Today ``dxf`` is the only
type that states anything, so sheet metal instructions have to be read from a DXF
in practice -- but not by anything's design.

Both of the usual spellings are read, and either may be used:

.. code-block:: text

  1001 PARTCAD          the APPID, as DXF requires
  1000 angle=90         a key and its value in one string tag...
  1000 radius=1.5
  1000 direction=up

  1001 PARTCAD
  1000 angle            ...or the name, followed by the value as its own type
  1040 90.0

Keys are read case-insensitively -- ``ANGLE`` and ``angle`` are one key -- and
values are kept exactly as the file states them. What is carried per element is
its DXF type, its layer, its handle, where it is, and those key/value pairs; an
element with no extended data is still carried, with nothing against it, because
"this drawing annotates nothing" and "this line was left un-annotated" are
different answers. The layer filters above apply, so the annotations describe
what is in the sketch and not what was filtered out of it.

They describe a block's **contents**, where the references put them, rather than
the references: a bend line drawn once in a block and placed twice is two
annotated lines. Each is named by the handle of its entity in the block
definition -- the one a person opening the file finds -- and lists the handles
of the references that placed it, outermost first. What a reference says, its
contents say too, unless they say otherwise: a reference annotated
``angle=90`` says it of every line its block draws.

``pc info`` on the sketch prints them, under ``Annotations``, beside what the
drawing says about *itself*: which DXF it is, what ``$INSUNITS`` says its
numbers are in and how much the sketch was scaled by (``mm per unit``), and --
under ``Layers`` -- **every** layer the file has, with
how many elements of which types are on each and whether this sketch reads it.
That last is not the question the annotations answer, and it is why the drawing
is described as well as read: a layer filter that matched nothing and a layer
that is not in the file both produce a sketch with nothing in it.

A STEP file states the same kind of thing in its own vocabulary -- a
``PROPERTY_DEFINITION`` hung on a product or on one named feature of one, and
``PRESENTATION_LAYER_ASSIGNMENT`` for its layers -- and ``pc info`` on a
``step`` part or assembly reports those under ``Properties`` and ``Layers``,
with the keys lower-cased the same way.

SVG
===

A sketch can be defined using an `SVG <https://en.wikipedia.org/wiki/SVG>`_ file.
Such sketches are declared using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: svg
      desc: <(optional) textual description>
      path: <(optional) filename> # otherwise "<sketch-name>.svg"
      use-wires: <(optional) boolean>
      use-faces: <(optional) boolean>
      ignore-visibility: <(optional) boolean>
      flip-y: <(optional) boolean>

CAD Scripts
===========

See the "CAD Scripts" section in the "Parts" chapter below.
