#################
Making and buying
#################

=====================
Manufacturing methods
=====================

The ``manufacturing.method`` field says how a part is made:

+------------------+-----------------------------------------------------------+
| Method           | Meaning                                                   |
+==================+===========================================================+
| ``additive``     | Built up, e.g. 3D printed                                 |
+------------------+-----------------------------------------------------------+
| ``subtractive``  | Cut away from stock -- see :ref:`subtractive`             |
+------------------+-----------------------------------------------------------+
| ``forming``      | Shaped without adding or removing material                |
+------------------+-----------------------------------------------------------+
| ``sheet_metal``  | A flat piece bent to shape -- see :ref:`sheet-metal`      |
+------------------+-----------------------------------------------------------+
| ``pcbBasic``     | A printed circuit board (**not implemented yet**)         |
+------------------+-----------------------------------------------------------+

These are ways of making a **part**, and apply to parts only. An assembly is put
together rather than made, and has a single method of its own -- see
:ref:`manufacturing an assembly <assembly-manufacturing>` below.

A part that is bought rather than made carries ``vendor`` and ``sku`` instead of
a method.

.. _subtractive:

Subtractive
-----------

``subtractive`` is the method that takes material away: a router, a laser, a
saw, a drill. What it says about a part is not a property of the part's own
shape -- almost any solid can be machined out of a big enough block -- but a
relation between the part and what it is made *from*, and between the part and
the machine that makes it. Both can be declared, and both are checked.

The stock it is cut from
^^^^^^^^^^^^^^^^^^^^^^^^

``source`` names the piece the part is cut out of:

.. code-block:: yaml

  parts:
    stock_plate:
      type: build123d      # bought, so it declares no method of its own
      path: stock_plate.py

    bearing_block:
      type: build123d
      path: bearing_block.py
      manufacturing:
        method: subtractive
        source: stock_plate

Cutting can only ever remove material, so the part has to be what is left of the
stock. ``pc test`` asks both halves of that, because each catches a different
mistake and neither implies the other:

- **Nothing of the part is outside the stock.** A part that pokes out of what it
  is cut from cannot be made from it however good the machine is -- most often
  the stock is simply too small, or the part is positioned off it.
- **The stock is bigger than the part somewhere.** A part that fills its stock
  exactly is one whose ``source`` names itself, or a copy of itself, which is
  the mistake a reader of the YAML cannot see.

``source`` is **required**, the way :ref:`sheet-metal`'s two fields are, and for
the same reason: subtraction is defined by what it starts from. A shape somebody
arrived at is not a subtractive part -- what makes it one is that it is what is
left of a piece that existed first -- so a declaration naming no stock has not
said what the method means.

A part genuinely made from no stock is a part made some other way: bought
(``vendor``/``sku``), ``additive``, or ``forming``.

.. _subtractive-machines:

The machine it is cut on
^^^^^^^^^^^^^^^^^^^^^^^^

Subtraction is one idea, but the machines that do it are not interchangeable,
and what they **cannot** do is the useful thing to know. A machine is named by
adding its own subsection:

.. code-block:: yaml

  manufacturing:
    method: subtractive
    source: stock_sheet
    laser:
      kerf: 0.15         # what the beam itself removes
      toolAxis: -Z       # the axis it fires along ('along: -Z' says the same)

+----------------+------------------------------------------------------------+
| Subsection     | The machine, and what it cannot do                         |
+================+============================================================+
| *(none)*       | A CNC router or mill. It follows any 2.5D path, so there   |
|                | is nothing it is held to beyond fitting its stock.         |
+----------------+------------------------------------------------------------+
| ``cnc:``       | The same machine, said out loud.                           |
+----------------+------------------------------------------------------------+
| ``laser:``     | A laser cutter. Its beam does not tilt, so every wall it   |
|                | makes is parallel to the axis it fires along.              |
+----------------+------------------------------------------------------------+
| ``drill:``     | A drilling machine. It goes in and comes out, so the only  |
|                | thing it makes is a **round** hole along its own axis.     |
+----------------+------------------------------------------------------------+
| ``cut:``       | A saw that cuts the stock across -- a board to length, a   |
|                | sheet to size. It makes **nothing but the stock with its   |
|                | ends cut off**, where its cuts say. See                    |
|                | :ref:`subtractive-cut`.                                    |
+----------------+------------------------------------------------------------+

Naming none of them means CNC. That is the machine that can make anything the
other two can, so it is the answer that is never wrong -- and it is what every
``subtractive`` part written before machines could be named already meant.

**Several may be named, and they are alternatives rather than stages.** A part
that declares both ``laser:`` and ``cnc:`` is claiming it could be made either
way, and ``pc test`` answers for both claims. ``pc cam`` then has to be told
which one to write for -- ``pc cam -m laser :gasket`` -- because a default
nobody picked is a program for the wrong machine; the file it writes is named
after the machine (``gasket.laser.nc``), so the alternatives land beside each
other rather than one overwriting the other. A part that really is machined in
*stages* is not this: it is a chain of parts, each naming the previous one as
its ``source``.

**Only ``subtractive`` has a machine at all**, and the keys that describe a cut
are refused everywhere else rather than accepted and never read. A ``diameter:``
on a part that says ``method: additive`` is a number somebody chose and nothing
acts on, which is the whole reason the job moved out of a section of its own --
a printer has feeds and speeds too, and the day PartCAD writes a program for one
they will be a printer's keys under a printer's subsection rather than a
router's read by accident. A *sketch* is the one section with no ``method:`` in
it: a drawing is not made out of anything, so it names the machine and the job
and nothing else.

Every machine takes a ``toolAxis``, which is the axis the tool, the beam, the
drill or the saw approaches along, written as one of ``+X``, ``-X``, ``+Y``, ``-Y``, ``+Z``
or ``-Z``. It defaults to ``-Z``: the part sits on the bed and the tool comes
down to it. Every machine also takes it as ``along:`` -- the same key, the way
it is usually said ("the laser cuts along -Z") -- and a subsection writes one or
the other, never both. It is **not** ``direction:``, which says which way round a
contour is cut (climb or conventional) -- the two reach one implementation in
one request, which is why they do not share a name. A laser also takes a ``kerf``, the width the beam itself removes,
which is a property of that machine and that material rather than of the job --
which is why it is a property of the machine rather than of the cut.

What ``pc test`` checks
^^^^^^^^^^^^^^^^^^^^^^^

Beyond the stock, one question per limited machine, and each applies **only to a
part that named that machine**:

- ``manufacturability-laser`` -- every face of the part is either a wall along
  the beam or a face across it. A chamfer, a taper, a dome or a fillet rolling
  over an edge is none of those, and there is no orientation of a beam that
  produces a surface at an angle to itself.
- ``manufacturability-drill`` -- the same, and every wall is round. This one
  is asked of what the machine **took away** rather than of the part, where the
  part names a ``source``: a drilled plate's straight sides came with the stock,
  and asking the part's own walls would fail every plate for having them.
- ``manufacturability-cut`` -- the stock, cut where every declared cut says,
  **is** the part. See :ref:`subtractive-cut`.

The first two are measured by sampling each face's own normal against the axis, not by
reading its surface type. The type is not the question: a cylinder is a wall
when it is coaxial with the axis and a defect when it lies across it, and a
surface extruded along the axis is a perfectly good wall whatever it is made of.

What is deliberately **not** checked is thickness, material or power. A laser
will cut a 20 mm plate as readily as a 1 mm sheet given enough of it, and how
much is enough is a property of the machine and the material rather than of the
design -- so it is not something PartCAD can answer from the geometry, and a
check that guessed would refuse parts the shop next door cuts every day.

What ``pc cam`` writes
^^^^^^^^^^^^^^^^^^^^^^

The same ``gcode`` file type produces a different program for each machine, and
which one it writes for is the part's own statement rather than a job parameter
-- what a part is made on is a property of the part, and a re-tunable key for it
would be a route written for a machine nobody owns.

+----------------+------------------------------------------------------------+
| Machine        | The program                                                |
+================+============================================================+
| CNC            | Contours offset by the cutter's radius, cut at stepped     |
|                | depths. ``M3``/``M5`` where a ``speed`` is named.          |
+----------------+------------------------------------------------------------+
| Laser          | One pass, offset by half the ``kerf``, with the beam gated |
|                | ``M3 S<power>``/``M5`` around each contour and no Z motion |
|                | at all. Reads no ``tool`` and no ``depth_per_pass``.       |
+----------------+------------------------------------------------------------+
| Drilling       | A rapid to each round feature's centre, a plunge and a     |
|                | retract, broken into steps where ``peck:`` says.           |
+----------------+------------------------------------------------------------+

A ``cut:`` gets no program: a saw cutting stock to size is told where to cut
and nothing else, and the part's declaration already says that. ``pc cam``
passes over a part that is only cut, and refuses ``-m cut``.

``power`` (a laser's S-word) and ``peck`` (how deep a drill goes before clearing
the swarf) join the other :ref:`cam job keys <cam-section>`. A part declaring a
``toolAxis`` other than ``-Z`` is rotated into the machine's frame before the
route is written, so the program is in the coordinates the part is fixtured in.

``examples/produce_part_subtractive`` is the whole of the above in one package:
two stocks, a laser-cut blank and gasket, a routed block whose chamfer is the
one feature only a router can make, a drilled plate, and a rail cut to length
off a board. The blank is what :ref:`sheet-metal` bends. The desk in
``//pub/furniture/workspace/basic`` is cut, every piece of it, with ``cut:``.

.. _subtractive-cut:

Cutting stock to size
^^^^^^^^^^^^^^^^^^^^^

``cut:`` is the machine most parts that are cut at all are cut on: a saw taking
a stud off an eight foot 2x4, or a shelf out of a sheet of plywood. It follows
no outline, so it is described by **where** it cuts, in the part's own
coordinates, which are also its stock's:

.. code-block:: yaml

  parts:
    leg:
      type: enrich
      source: //pub/std/imperial/dimensional-lumber:lumber
      with:
        width: 4
        height: 4
      manufacturing:
        method: subtractive
        source: //pub/svc/commerce/homedepot:lumber/4x4x8
        cut:
          toolAxis: +Y          # the axis the saw travels along, for every cut ('along:' too)
          cuts:
            # How far into the stock the saw travels before it cuts across.
            - length: $length in
            # A cut may travel along an axis of its own; 'along:' says the same.
            # - toolAxis: -X
            #   length: 3 in

A saw is written the way every other machine is: by its ``toolAxis``, which
points at the **offcut**. Each cut starts where the stock starts along that
axis -- the way a board is measured from its end -- travels ``length:`` into it,
and cuts across; everything further along the axis is cut off, and what is
behind the saw is the part. So ``toolAxis: -Y`` counts from the other end.

- ``length:`` is always there: it is the whole of *where*.
- ``toolAxis:`` on a cut, or ``along:`` -- which says the same, the way a saw
  cut is usually said; one or the other -- is the axis that cut travels along,
  as an axis (``+Y``) or a vector (``[0, 1, 0]``).
- A cut that names neither travels along the machine's ``toolAxis:`` (or
  ``along:``), and a machine that names none has the default every machine
  has, ``-Z``.

Any number in a cut may be written as ``$name`` -- the value of the part's own
parameter of that name, with a unit after it if it needs one (``$length in``).
A part cut to length is nearly always parametric, and a cut written as a number
would be right for one instance and wrong for every other.

``pc test`` runs ``manufacturability-cut`` over it, which makes each cut in the
stock in turn and compares what is left with the part. Whatever the part has
that the cut stock does not is a feature no saw made; whatever the cut stock has
that the part does not is a notch, a hole or a cut in the wrong place; and a cut
that takes nothing off the stock is one that misses it -- usually a length
longer than the board, or an axis pointing the wrong way. Each of the three is a
failure that says which plane it was about.

.. _sheet-metal:

Sheet metal
-----------

``sheet_metal`` is the one method that is not described by the part alone. The
others say how a shape is produced from stock; this one says that an existing
flat piece was put through a brake, so it names two things instead:

.. code-block:: yaml

  parts:
    bracket:
      type: step
      manufacturing:
        method: sheet_metal
        source: blank                              # the part that is bent
        instructions: bends;include=BEND_UP,BEND_DOWN   # the sketch that says how
      tolerance: 0.1

- ``source`` -- **required.** The part that goes into the brake: the flat blank.
  It is a reference, resolved against this package like every other reference a
  part makes, and it points at a **part** rather than at a drawing because it is
  one. It has a thickness, a material, a tolerance, and a manufacturing method of
  its own.

- ``instructions`` -- **required.** The sketch that says where the bends are and
  what each of them is. It is a reference to a :ref:`sketch <sketches>`, so it
  may carry parameters: a drawing that holds the outline *and* the bend lines is
  read as bends alone with ``;include=BEND_UP,BEND_DOWN``, which is what the
  DXF layer parameters are for.

The outline belongs to the blank
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

The outline of the part, its holes, its slots and its cut-outs are **not** the
sheet metal process's to make, and must not be described as part of it. They
belong to the blank, which is usually cut flat -- laser, waterjet, punch,
router -- and so is usually an ordinary ``subtractive`` part:

.. code-block:: yaml

  parts:
    sheet:
      type: step                # the stock, 2 mm, bought by the sheet

    blank:
      type: extrude
      sketch: outline           # the flat pattern, holes and all
      depth: 2.0
      manufacturing:
        method: subtractive     # laser cut, and that is where the holes come from
        source: sheet
      parameters:
        tolerance: 0.1

    bracket:
      type: step
      manufacturing:
        method: sheet_metal
        source: blank
        instructions: bends;include=BEND_UP,BEND_DOWN

That is how it is made, and so it is how it is written down. A shop cuts the
flat pattern on one machine and bends it on another, they are quoted, toleranced
and scheduled separately, and the flat pattern is a thing that exists -- it is
what arrives at the brake. Describing a hole as part of the bending step would
put it on the process that cannot make it, and would leave the part with no
declaration of the process that can.

``subtractive`` is the usual answer rather than a required one: what has to be
true of a ``source`` is that it is flat, which is what ``pc test`` asks of it. A
blank that is bought in rather than made has no manufacturing method to declare,
one sheared or punched to outline is ``forming``, and an ``alias`` or an
``enrich`` of a part declared elsewhere carries whatever that one says. All of
them are blanks, and the check takes them.

What ``pc test`` checks
^^^^^^^^^^^^^^^^^^^^^^^

Two questions, one about each half of the declaration:

- **The blank is flat, top and bottom.** What goes into a brake is a piece of
  sheet, so the horizontal plane through its highest point and the one through
  its lowest each meet it in an area rather than touching it at a point. A
  ``source`` that fails this is not a blank -- most often it is the bent part
  itself, named by mistake.

- **Every bend line says what kind of bend it is.** Each line of the
  instructions sketch carries three annotations:

  +-----------------+----------------------------------------------------------+
  | Annotation      | What it has to be                                        |
  +=================+==========================================================+
  | ``angle``       | How far the metal is turned, in degrees. Positive.       |
  +-----------------+----------------------------------------------------------+
  | ``radius``      | The **inner** radius of the bend, in millimetres. More   |
  |                 | than zero -- zero is a fold, not a bend.                 |
  +-----------------+----------------------------------------------------------+
  | ``direction``   | ``up`` or ``down``; letter case does not matter.         |
  +-----------------+----------------------------------------------------------+

  Where they come from is the sketch's business, not this check's: a DXF states
  them as :ref:`extended data <sketch-annotations>`, and the check reads what the
  sketch reports rather than the file it was read from.

What is *not* checked is the geometry of the part against those instructions.
Whether bending the blank as described produces the shape the part declares is a
question for the day PartCAD bends the blank itself; until then the part is what
its own type built, and these are the manufacturing inputs beside it.

``examples/produce_part_sheet_metal`` is the whole of the above in one package:
one DXF holding the flat pattern and two bend lines, a blank extruded from the
outline layer, and three parts folded from that one blank -- at one bend line,
at the other, and at both. They differ in nothing but which layers their
``instructions`` select, which is the case the layer parameters exist for.

.. _procurement:

===========
Procurement
===========

A part that can be bought off the shelf instead of being manufactured is
declared using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      # ...
      vendor: <(optional) the name of the vendor selling the part>
      sku: <(optional) the vendor's stock keeping unit (SKU) of the part>
      count_per_sku: <(optional) the number of parts in one SKU, 1 by default>
      item_in_sku: <(optional) which of the kinds of items in the SKU this is>

- ``vendor``

  Optional. The vendor that sells the part.

- ``sku``

  Optional. The vendor's `stock keeping unit
  <https://en.wikipedia.org/wiki/Stock_keeping_unit>`_ identifying what is
  ordered from that vendor.

  Both ``vendor`` and ``sku`` must be set for the part to be considered
  purchasable. If either is missing, the part has to be manufactured instead,
  which relies on the MCFTT parameters described above.

- ``count_per_sku``

  Optional. Defaults to ``1``. Must be a positive integer.

  The number of parts that come in a single SKU, for the parts that are sold in
  packs: a bag of 25 nuts is one SKU that yields 25 parts. Providers use it to
  translate the number of parts requested into the number of SKUs to order, and
  the number of SKUs a store has in stock into the number of parts it can
  supply.

- ``item_in_sku``

  Optional. Which item this is, where one SKU is a *set* of different things
  rather than a pack of one: a shaft sold with the clip that goes on it, a
  bracket that comes with its screws. Each of them is an object of its own --
  used on its own, assembled on its own, possibly taken apart and put back
  later -- so each is declared as a part of its own. Each names the set's
  ``vendor`` and ``sku``, and says which item of the set it is:

  .. code-block:: yaml

    parts:
      shaft_72mm:
        type: step
        vendor: gobilda
        sku: "2106-4008-0720"
        item_in_sku: shaft
      shaft_72mm_clip:
        type: step
        vendor: gobilda
        sku: "2106-4008-0720"   # the same set
        item_in_sku: clip

  ``count_per_sku`` is then how many of that one kind come in a set. What is
  ordered is the set, as many times as the most demanding kind needs: two
  shafts and two clips are two sets, not four. Objects of one SKU that do not
  name an ``item_in_sku`` are one kind with each other, which is what a SKU of
  one kind of thing is.

  An object sold in more than one set -- the same clip comes with every length
  of shaft -- is declared once for the geometry, with an ``alias`` of it for
  each set it comes in, the way a part sold by several vendors is (below).

These values are passed on to providers of the type ``store`` as
``request["vendor"]``, ``request["sku"]``, ``request["count_per_sku"]`` and
``request["item_in_sku"]`` (see :ref:`providers`). A cart also says what to
order, one line per SKU, in ``request["cart"]["skus"]``.

.. _made-from-stock:

Parts that are made
-------------------

A part with manufacturing instructions -- a ``manufacturing:`` section naming a
method -- is **made**, and whoever builds the assembly is taken at their word
that they can make it: PartCAD has the instructions, and for now assumes the
capabilities to follow them. So nobody is asked to supply such a part. What has
to be procured is what it is made *from*: the ``source:`` of its
``manufacturing:`` section, which is procured by the same rule in turn -- a
bracket bent from a blank that is cut from a sheet is procured as the sheet. A
part made from nothing it names (``additive``, ``forming``) needs nothing
procured at all.

- **The bills of materials** list every part that goes into the assembly, and
  beside them a **Stock** section: what the made parts are made from, one piece
  for each part made from it, and which parts each is for. Cutting several parts
  out of one piece is a question of layout that PartCAD does not answer yet, so
  the count is what buying for each part separately would take -- an upper
  bound, never short. The detailed bill of materials (``pc bom``) lists what
  has to be procured: a made part is not a line item of its own there but the
  stock it is made from, of kind ``stock``, with the vendor and the SKU to
  order it by.
- **The assembly instructions** open, after the bill of materials, with the
  parts to manufacture: each one, how many of it, what it is made from, and its
  manufacturing instructions written out in full.
- **pc supply** puts the stock in the cart instead of the part.
- **pc test** does not look for a supplier of a made part. It checks that its
  instructions are complete (a tolerance), and that its stock can be had -- by
  running the same tests over the stock, which for a bought one is a supplier
  that carries it.

A part that has manufacturing instructions **and** a ``vendor`` and an ``sku``
can be had either way. It is tried as bought first: ``pc test`` asks for a
supplier, and only if no supplier confirms it does it check that the part can be
made instead. The bills of materials and the cart list it as bought.

Note that ``count_per_sku`` is a property of how the part is packaged for sale,
not of the CAD model. If the same part is sold by several vendors in different
pack sizes, declare one part per (vendor, SKU) pair, for example using
``alias``.

.. code-block:: yaml

  parts:
    nut_m4_0_7mm:
      type: step
      vendor: gobilda
      sku: "2803-0004-0002"
      count_per_sku: 25  # sold in bags of 25

    # The same nut, ordered from somewhere else. What it is stays where it is
    # declared; only what it is bought as is restated here.
    nut_m4_0_7mm_from_mcmaster:
      type: alias
      source: nut_m4_0_7mm
      vendor: mcmaster
      sku: "90592A090"
      count_per_sku: 100

What an object is bought as is the one thing an ``alias`` or an ``enrich`` may
state of its own: everything else it reports -- where the file is, what it is
built with, which parameter values it has -- belongs to the declaration it
resolves to. A reference that names a ``vendor`` or an ``sku`` replaces the
whole record, ``count_per_sku`` included, because a pack size written for one
SKU says nothing about another one; an absent ``count_per_sku`` therefore reads
as ``1``, the same as it would on a part declared outright. A reference that
names neither is ordering the same thing, so the record stands -- and a
``count_per_sku`` on its own corrects how many of that same SKU arrive in one.

This travels down a chain: an alias of an alias, and an enrich of an enrich,
report what the reference in the middle declared rather than only what is at
the end of the chain.

.. _materials:

=========
Materials
=========

A part is made of something, and ``materials`` is where a package says what
that something is. It is the object the ``material`` parameter of a part points
at (see :ref:`parameters`), so that naming a substance is naming a thing PartCAD can
ask questions of rather than repeating a string every reader has to interpret
for themselves.

A material is **not** a shape. PLA has no geometry: there is nothing to render,
to export or to tessellate, and none of what :ref:`parts` and :ref:`assemblies`
can do applies to it. What it is, is a set of facts about a substance:

.. code-block:: yaml

  materials:
    <material name>:
      formal: <(optional) the short formal name, e.g. "PLA">
      full: <(optional) the full name, e.g. "Polylactic Acid">
      desc: <(optional) textual description>
      url: <(optional) where to read about it>
      density: <(optional) density in g/mm^3>
      mu: <(optional) coefficient of sliding friction, dimensionless>
      tags: <(optional) a list of free-form tags, or a single tag>

The short form gives the full name and nothing else:

.. code-block:: yaml

  materials:
    nylon: Nylon

Density is in ``g/mm^3``, the units every length in PartCAD is already in, so
that a mass falls out of a volume without a conversion nobody remembers to
apply. Datasheets quote ``g/cm^3``, which is 1000 times larger: PLA at
1.32 g/cm^3 is declared as ``0.00132``. A material that states no density
reports no mass, rather than a mass of zero -- nothing downstream could tell an
invented figure apart from a stated one.

A part made of a material is weighed at its density wherever PartCAD writes a
mass: the URDF exporter, and the simulation formats a plugin writes, compute
each part's mass, centre of mass and inertia from its solid and the density of
what it is made of, unless the part states its own ``mass``. The density
reaches them as the part's ``density`` property in kg/m³, the unit every
simulation format states one in (see :ref:`properties`).

``tags`` is free-form on purpose. There is no controlled vocabulary of material
properties that survives contact with real catalogues, and imposing one would
only mean packages could not say what they mean.

Materials are addressed like every other object, as ``<package>:<name>``, so a
part in one package names a material catalogued in another:

.. code-block:: yaml

  parts:
    bracket:
      type: cadquery
      parameters:
        material:
          type: string
          default: //pub/std/manufacturing/material/plastic:pla

List what a package catalogues with ``pc list materials`` (and
``pc list materials //...`` to walk the packages it imports).

Standard catalogues
-------------------

The PartCAD index publishes two families of standard materials, so that a part
made of something ordinary need not restate any of the above:

- ``//pub/std/manufacturing/material/plastic`` -- polymers: the commodity and
  printable thermoplastics (``pla``, ``abs``, ``asa``, ``petg``, ``pc``), the
  engineering ones (``nylon``, ``pa12``, ``pa66-gf30``, ``pom``, ``uhmwpe``),
  the high-performance ones (``ptfe``, ``peek``, ``pei``, ``pps``), the
  polymer-matrix composites (``cfrp``, ``gfrp``) and the elastomers (``tpu``,
  ``nr``, ``nbr``, ``epdm``, ``fkm``, ``silicone``).

- ``//pub/std/manufacturing/material/metal`` -- metals and alloys, named by
  their standard designation and temper: ``al-5052-h32``, ``al-6061-t6``,
  ``al-7075-t6``, ``steel-4130``, ``ss-316l``, ``ti-6al-4v``, ``inconel-718``
  and the rest of what robotics, aviation and automotive parts are made of.

An alloy is named ``<metal>-<designation>-<temper>`` rather than by the bare
designation for two reasons: ``5052:`` in YAML is the *number* 5052 rather than
a name, and a temper is part of what was ordered -- 6061-T6 and 6061-O are one
alloy and not one material to build out of.

.. _software:

========
Software
========

A product is rarely hardware alone: the board in it runs a firmware image, the
controller boots a disk image, the tool that talks to it is a binary on the
host. ``software`` declares those as objects of the package, beside its parts
and its assemblies.

Software is **not** a shape. There is no geometry to render, to export or to
measure, and none of what :ref:`parts` and :ref:`assemblies` can do applies to
it. What it is, always, is a *file*:

.. code-block:: yaml

  software:
    <software name>:
      type: raw # (optional) "raw" is the default and the only type so far
      desc: <(optional) textual description>
      version: <(optional) the version of this software>
      url: <(optional) where to read about it>
      path: <(optional) the file, relative to the package>
      fileFrom: <(optional) where to fetch the file from; see "Files">
      fileUrl: <(optional) the URL to fetch it from>
      fileHash: <the bytes to expect; required with "fileFrom", see "Files">

The short form declares nothing but the path:

.. code-block:: yaml

  software:
    service-tool: tools/service-tool.sh

``path`` behaves as it does everywhere else (see :ref:`files`): without it the file
is the object's own name, and a file the package does not carry is declared with
``fileFrom``/``fileUrl`` and fetched lazily. The default path carries no
extension, because a firmware image is as likely to be a ``.img``, a ``.uf2`` or
nothing at all as it is a ``.bin``.

``raw`` is the file handed over as it is: PartCAD carries it, says which one it
is, and what to do with it is the reader's business. Every type is a file and
that will not change -- the types that come after ``raw`` name the *procedure*
the file goes through rather than a different kind of object, associating a
specific firmware flashing procedure (which tool, which bootloader, which reset
dance) with the image.

Which software an object ships with
-----------------------------------

A part or an assembly says what it ships with in its own ``software`` list. A
bare name is software of the same package; a qualified one is software of
another:

.. code-block:: yaml

  parts:
    controller:
      type: step
      software:
        - controller-firmware
        - //vendor/blobs:radio-firmware

  assemblies:
    device:
      type: assy
      # The host-side tool is the whole device's, not any one board's.
      software:
        - service-tool

``software`` is optional, and most parts declare none. A single one may be
written on its own instead of as a list (``software: controller-firmware``).
Declaring it is what puts the file into the bill of materials of every assembly
the part ends up in, and what makes ``pc test`` insist the file be obtainable
(see `Manufacturability`_ below).

The reference is resolved against the package that *wrote* it, so an ``alias``
or an ``enrich`` of that part in another package still points at the same file.

In the bill of materials
------------------------

Every assembly's bill of materials lists the software of the parts and
sub-assemblies it is made of, and its own, under a heading of its own:

.. code-block:: shell

  $ pc bom :device
  Bill of materials of //robot:device:
          //robot:controller  2  The controller board
  Total: 2
  Software:
          //robot:controller-firmware  2  //robot@8f1c...  The image the board is flashed with
          //robot:service-tool         1  //robot@8f1c...
  Software total: 3

Each software line names the package it came from **and the revision of that
package** -- the commit its files were read at. A bracket is the same bracket
whenever it is fetched; a firmware image is a different file as soon as its
package publishes again, so the revision is what makes the line mean something.
A package that is not in a git repository has no revision, and the line says so
rather than inventing one.

The count is how many times something in the assembly needs it: three boards
running one image is a count of three, the same way three of anything else is.
A sub-assembly that is bought whole -- it declares a vendor and an SKU, and a
supplier has it available -- is not expanded, so its firmware is no more a line
item than its screws are.

Software is not procured: ``pc supply`` and the manufacturability tests walk the
hardware only, because nobody sells a firmware image.

In the package's README
-----------------------

``pc render -t readme`` lists the software of a package in a table of its own,
saying which file each one is, the version it declares, and the hash it is
pinned to. The file is linked where the package carries it; where it is fetched,
the URL it comes from is shown instead.

Which file is it?
-----------------

The whole point of listing software beside the hardware is being able to say
which file went into a product. There are two ways a package can be that
specific, and ``pc lint`` requires one of them (the ``Software`` check):

- The package **carries the file**. It is content of the repository, so the
  revision recorded beside every software line item identifies it exactly.
- The package **pulls it in** with ``fileFrom``, and pins it with ``fileHash``.
  Without a hash nothing identifies it: the URL serves whatever it serves at the
  moment it is fetched, and the same package revision produces a different image
  tomorrow.

.. code-block:: yaml

  software:
    # In this repository: its revision says which file it is.
    controller-firmware:
      path: controller-firmware.bin

    # Not in this repository: pinned by hash.
    radio-firmware:
      fileFrom: url
      fileUrl: https://example.com/vendor/radio-1.4.bin
      fileHash: sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae

``fileHash`` is not a software-specific idea: it pins the bytes of any file a
package fetches rather than carries, and the download is refused unless they
match (see :ref:`file-hash` for the spelling and the details). Everywhere it is
required for the object to be manufacturable; software is the one kind where a
missing one is reported by ``pc lint`` as well, before anything is built.

See ``examples/produce_software`` for a package that does both, and
``examples/produce_part_kicad`` for a board that pulls its host-side tool from a
public URL.

Manufacturability
-----------------

A board nobody can flash is not a board anybody can make. So the manufacturing
test (``pc test``, the ``manufacturability`` check) asks the same question of a part's
``software`` that it asks of everything else the part needs, and the part fails
unless all of it holds:

- every reference resolves to a software object;
- the file is there -- carried by the package, or fetched successfully;
- it matches its ``fileHash``, where one is declared;
- and the declaration is reproducible at all, which is the same
  ``fileFrom``-needs-a-``fileHash`` rule the part's own file is held to
  (:ref:`reproducibility`).

That applies whether the part is bought or made: buying the board does not
answer the question of which image goes on it. An assembly that declares
software of its own is held to the same rule; its parts' software is checked by
their own run of the test.

Software is otherwise absent from procurement -- ``pc supply`` walks the
hardware only, because nobody sells a firmware image.

.. _providers:

=========
Providers
=========

Providers are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  providers:
    <provider name>:
      type: <store|manufacturer|enrich>
      desc: <(optional) textual description>
      # ... type-specific options ...
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

    <enriched provider name>:
      type: enrich
      source: <provider name, or /path/to:provider-name>
      with:
        <param name>: <value>

``enrich`` providers are just references to other providers with some parameters
modified to specific values. ``with:`` sets any of the parameters the source
provider declares, the same way an ``enrich`` part's ``with:`` does, and under
the same rule: a value may not contain ``,``, ``;`` or ``=``. ``currency`` is
also read by PartCAD itself, as what the provider's quotes are in, so it has to
be a name such as ``USD``.

``store`` and ``manufacturer`` providers are implemented as Python scripts.
These scripts are invoked using the ``runpy`` module which allows to pass input
as values of global objects. The outputs are also extracted from the value of
global objects.

The input is passed as the dictionary ``request``.
The output is extracted from the dictionary ``output``

Store
-----

``store`` providers use the following input and output values:

- `request["parameters"]`: The configuration parameters of the provider.
- `request["api"]`: The API method called.

  - `request["api"] == "caps"`

    Get capabilities of this provider.
    Currently PartCAD does not use capabilities for ``store`` providers.

    - `output`: no output is expected

  - `request["api"] == "avail"`

    Check availability of the specific part.

    - `request["vendor"]`: the vendor of the part
    - `request["sku"]`: the SKU of the part
    - `request["count"]`: the requested quantity of the parts
    - `request["count_per_sku"]`: the known number of parts per SKU
    - `request["item_in_sku"]`: which item of the SKU this is, where the SKU is
      a set of several kinds of items, or `None`
    - `output["available"]`: boolean, whether it is available in this store

  - `request["api"] == "quote"`

    Get a quote for the specific cart of parts.
    Quote API is the core of the provider.
    It is expected to return the price of a cart.

    - `request["cart"]["parts"]`: the dictionary of parts
    - `request["cart"]["parts"][<id>]["vendor"]`: the vendor of the part
    - `request["cart"]["parts"][<id>]["sku"]`: the SKU of the part
    - `request["cart"]["parts"][<id>]["count"]`: the requested quantity of the parts
    - `request["cart"]["parts"][<id>]["count_per_sku"]`: the known number of parts per SKU
    - `request["cart"]["parts"][<id>]["item_in_sku"]`: which item of the SKU the part is,
      where the SKU is a set of several kinds of items (absent otherwise)
    - `request["cart"]["skus"]`: what to order, a list with one entry per SKU
    - `request["cart"]["skus"][<n>]["vendor"]`, `["sku"]`: the SKU
    - `request["cart"]["skus"][<n>]["count"]`: how many of that SKU to order,
      which is already worked out from `count_per_sku` and `item_in_sku`. Order
      from here rather than once per part: a SKU that is a set of several parts
      would otherwise be bought once for each of them.
    - `request["cart"]["skus"][<n>]["parts"]`: the parts that SKU is for
    - `output["price"]`: the total price of the cart
    - `output["cartId"]`: the id of the cart (to be used for the order later)

  - `request["api"] == "order"`

    Order the specific quote.
    Order API does not need to be implemented as there is no infrastructure
    for payments yet.

    - `request["cartId"]`: the id of the cart to be purchased

Manufacturer
------------

``manufacturer`` providers use the following input and output values:

- `request["parameters"]`: The configuration parameters of the provider.
- `request["api"]`: The API method called.

  - `request["api"] == "caps"`

    Get capabilities of this provider.

    - `output["materials"]`: the dictionary of supported materials

      .. code-block:: json

        {
            "//pub/std/manufacturing/material/plastic:pla": {
                "colors": [{"name": "red"}],
                "finishes": [{"name": "none"}]
            }
        }
    - `output["format"]`: the list of supported formats (e.g. `["step"]`)

  - `request["api"] == "quote"`

    Get a quote for the specific cart of parts.
    Quote API is the core of the provider.
    It is expected to return the price of a cart.

    - `request["cart"]["parts"]`: the dictionary of parts
    - `request["cart"]["parts"][<id>]["format"]`: the format of the binary (e.g. `"step"`)
    - `request["cart"]["parts"][<id>]["binary"]`: the geometry data
    - `output["price"]`: the total price of the cart
    - `output["cartId"]`: the id of the cart (to be used for the order later)

  - `request["api"] == "order"`

    Order the specific quote.
    Order API does not need to be implemented as there is no infrastructure
    for payments yet.

    - `request["cartId"]`: the id of the cart to be purchased
