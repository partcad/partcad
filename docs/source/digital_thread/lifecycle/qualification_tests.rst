Qualification tests
###################

``pc qual test`` holds an object to every claim its declaration makes that can be
measured. It is a list of tests, each asking one question of one object, each of
one of four subtypes (see :doc:`/digital_thread/lifecycle/qualification`); this
page is the list of the built-in ones, and it is the same text the Digital Thread
shows beside each test on the **Qualification** tabs.

In the UI
=========

**Qualification → Basic** and **Qualification → Topology** list the tests of
their subtype, and **Qualification → Other** the tests plugins supply that the
object declares. Basic is the first tab of the group and the one that is always
enabled, since every object of a package has tests.

- Down the left, every test of the tab's subtype, in the order they run, each
  with its verdict: passed, failed, warned, skipped, or not applicable -- the
  last saying *why*, so a test that did not apply is never mistaken for one that
  passed.
- In the middle, the test selected: what it found this time, and under that what
  the test asks, when it does not apply, what each failure means and what to do
  about it -- the text of this page, which is where it comes from.
- On the Topology tab, for a failure, where it is: each finding left behind as
  geometry, with **Show**, which opens it in the 3D view with the finding in a
  colour of its own and the rest of the object faded. An interference leaves the
  two parts that overlap, placed where the assembly places them, with what they
  share; ``tolerance-surfaces`` the part with the faces nothing tolerances;
  ``tolerance-edges`` the part with tubes along the edges nothing tolerances.
- On the Other tab, the report the plugin's tool wrote, as a table.

.. image:: /images/dt-validation.png
  :width: 100%
  :align: center
  :alt: The Qualification group's Basic tab: every test with its verdict, and the selected test explained

The tests **run** when a tab is first opened, as ``pc qual test --<subtype>
<object>`` runs them and through the same cache, so the panel and the command line
give the same answer; **Run again** asks afresh. An object that belongs to no
package -- a shape shown from a script -- has nothing to ask PartCAD about, and the
tab says so. ``pc ide view --qualification-basic`` (``-topology``, ``-other``)
opens one from a terminal.

On the command line
===================

.. code-block:: sh

  pc qual test <object>                          # a part; -a an assembly, -S a scene, -s a sketch
  pc qual test --topology <object>               # one subtype: --basic, --topology, --simulation, --other
  pc qual test -f interference -a gearbox        # only the tests whose name starts with this
  pc qual test -P <package>...                   # every object of a package and the packages below it

Every built-in test is asked of every object, and the tests that have nothing to
ask of it -- an assembly's tests of a part, the analyses of a part that declares
none -- say so and pass. Each verdict is one of:

- **passed**;
- **failed**: the claim does not hold, and the test says what it found;
- **warned**: a finding on an object nobody is going to make
  (``manufacturable: false``), reported and not failed;
- **skipped**: the question could not be put on this machine -- a solver that is
  not installed, a container runtime that is not running -- said out loud, and
  not failed;
- **not applicable**: the test has nothing to ask of this object, and says why.

A verdict is cached under everything it depends on, so asking again about an
object that has not changed costs a lookup; a failure, or a finding reported and
not failed (a **warning**, such as ``defects``'), read from the cache is said again
as "remembered from an earlier run", and ``pc --cache-bypass qual test`` asks
afresh. Asked about one object by name, a test may be stricter than when it is
walked to as part of a package -- ``sim`` fails a simulation with no condition to
check rather than skipping it.

A built-in test that takes parameters reads them from the object, as
``<object>.qual.<subtype>.<test>.<param>``: each test's **Settings** below says
which it takes.

The tests
=========

They are listed by subtype, and within one in the order they run: the nearly
free ones first, then those that measure geometry, then the analyses and the
simulations, which are the most expensive.

.. BEGIN GENERATED FROM partcad.qual.catalog: run 'poetry run python -m partcad.qual.catalog --write'

.. _qual-basic:

Basic
=====

Checks whose findings are words. ``pc qual test --basic`` runs these alone.

.. _test-cad:

``cad``: Builds
---------------

**Applies to** every part, assembly, scene and sketch. ``pc qual test -f cad <object>`` runs it alone.

Whether the object builds: its script runs, its file reads, its assembly puts together, and something comes out. It is the first question, and every other check that looks at geometry takes it as answered - a check that finds no shape to measure passes and leaves the failure here, so that one broken object is one failure and not a dozen.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Never: everything PartCAD tests is built first.

When it fails
^^^^^^^^^^^^^

* ``Failed to get the shape``: building it produced nothing. The reason is in the log above the verdict - the error the script raised, the file that could not be read or fetched, the link of an assembly that names an object nobody declares. Build it on its own to see it again: ``pc --no-ansi info <object>`` or ``pc --no-ansi render -t png <object>``.
* A verdict remembered from an earlier run is said again with "remembered from an earlier run": once the cause is fixed, ``pc --cache-bypass qual test`` asks again rather than reading the cache.

.. _test-manufacturability:

``manufacturability``: Can be made or bought
--------------------------------------------

**Applies to** every object that does not say ``manufacturable: false``. ``pc qual test -f manufacturability <object>`` runs it alone.

Whether the object can be had: bought from somebody who sells it, or made by a method it declares. It asks for exactly what ``pc supply`` would order and what ``pc instructions`` would tell somebody to do.

* Every object has to be reproducible: one read from a file the package fetches (``fileFrom:``) has to pin the file with ``fileHash:``, or name a vendor and SKU to order it by, so that it is known which bytes it is made from.
* A part is bought (``vendor:`` and ``sku:``, and a supplier that carries it) or made (``manufacturing:`` with a ``method:``). A part that is made needs a manufacturing tolerance, and the stock it is made from (``manufacturing: source:``) has to pass these checks itself. The ``software:`` it declares has to resolve, to the file that was meant.
* An assembly is either sold assembled (bought, and nothing inside it is looked at), or assembled: then every step has to be one somebody can follow - each item after the first says what it is joined to and how - and everything it is procured from has to pass these checks on its own.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

An object that says ``manufacturable: false`` - a model of something somebody else makes, an import kept as it arrived, a scene (which is not manufacturable unless it says so). A sketch is checked for being reproducible and for nothing else.

When it fails
^^^^^^^^^^^^^

* ``It is not reproducible: ...``: pin the file with ``fileHash:`` (``pc add`` writes one for an object it adds from a URL), carry the file in the package, or name a ``vendor:`` and ``sku:``.
* ``Cannot be purchased or manufactured``: add a ``manufacturing:`` section with a ``method:`` (see the ``manufacturability-*`` checks for each method), or a ``vendor:`` and ``sku:`` - or say ``manufacturable: false`` if nobody is going to make it.
* ``No suppliers found`` / ``No suppliers provide the part``: name a supplier that carries it, or make it instead.
* ``No manufacturing tolerance is specified``: give the part a ``tolerance``, which a part that is made needs to be made to anything.
* ``The stock '...' it is made from is not found`` / ``cannot be had``: fix the name under ``manufacturing: source:``, or make the stock obtainable.
* ``Step '...' can't be followed: ...``: give that link a ``connect:`` and say how it goes on - a ``how:``, or a mating or an interface that says it.
* ``Missing part or assembly '...' is referenced`` / ``Non-manufacturable ... is referenced``: what the assembly is made of has to exist and be manufacturable.

Settings
^^^^^^^^

``manufacturable:`` on the object or its package; ``vendor:``, ``sku:``, ``fileFrom:``, ``fileHash:``, ``software:``, ``manufacturing:`` and the part's ``tolerance``.

.. _test-manufacturability-additive:

``manufacturability-additive``: Additive: a closed solid to print
-----------------------------------------------------------------

**Applies to** a part with ``manufacturing: method: additive``. ``pc qual test -f manufacturability-additive <object>`` runs it alone.

Whether a part to be printed can be: its declaration can be read, and what is printed is a closed solid - a body with no open edges, which is what a slicer needs to know what is inside it. What is printed is the design the part names under ``manufacturing: source:``, or the part itself where it names none.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part made by any other method.

When it fails
^^^^^^^^^^^^^

* ``The additive declaration says ...``: the ``fff:`` printer has a key it does not take or a value it cannot read, a printer's setting is written directly under ``manufacturing:`` instead of under ``fff:``, a cut's key is written on a printed part, or a ``visual:`` is written there rather than on the part itself; the sentence names which.
* ``The design '...' it is printed from is not found``: fix the name under ``manufacturing: source:``.
* ``The design '...' is not solid`` / ``The shape is not solid``: what is printed has open edges - faces that do not meet. Close the model in the tool it comes from, or export it as a solid rather than as a surface.
* ``Failed to get the shape``: it did not build; see ``cad``.

Settings
^^^^^^^^

``manufacturing:`` - ``source:`` (the design) and ``fff:`` (the printer: ``toolAxis`` or ``along``, ``nozzle``, ``filament``, ``layerHeight``, ``lineWidth``, ``walls``, ``topLayers``, ``bottomLayers``, ``infill``, ``infillPattern``, ``feed``).

.. _test-manufacturability-subtractive:

``manufacturability-subtractive``: Subtractive: cut from its stock
------------------------------------------------------------------

**Applies to** a part with ``manufacturing: method: subtractive``. ``pc qual test -f manufacturability-subtractive <object>`` runs it alone.

Whether a part to be cut out of stock can be: the stock is named, the machine sections can be read, the part is a closed solid, and it lies inside its stock with material to take away. Cutting removes material and never adds it, so a part that sticks out of its stock cannot be cut from it.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part made by any other method.

When it fails
^^^^^^^^^^^^^

* ``The subtractive declaration states no 'source'``: name the stock the part is cut from under ``manufacturing: source:``.
* ``The subtractive declaration says ...``: a ``cnc:``, ``laser:``, ``drill:`` or ``cut:`` section has a key it does not take, or a value it cannot read; the sentence names it.
* ``It does not fit the stock '...': ... mm3 of it is outside``: make the stock larger, or place it so that it encloses the part.
* ``The stock '...' is the same solid as the part, so nothing is cut from it``: ``source:`` names the part itself, or a copy of it; name the blank instead.
* ``The shape is not solid``: close the model, as for ``manufacturability-additive``.

.. _test-manufacturability-forming:

``manufacturability-forming``: Forming: a closed solid
------------------------------------------------------

**Applies to** a part with ``manufacturing: method: forming``. ``pc qual test -f manufacturability-forming <object>`` runs it alone.

Whether a part to be formed - moulded, cast, pressed - is a closed solid.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part made by any other method.

When it fails
^^^^^^^^^^^^^

* ``The shape is not solid``: the part has open edges; close the model.
* ``Failed to get the shape``: it did not build; see ``cad``.

.. _test-manufacturability-sheet-metal:

``manufacturability-sheet-metal``: Sheet metal: a flat blank and bends
----------------------------------------------------------------------

**Applies to** a part with ``manufacturing: method: sheet_metal``. ``pc qual test -f manufacturability-sheet-metal <object>`` runs it alone.

Whether a sheet metal part can be bent out of what it names: a blank that is flat on both faces (``source:``), and a sketch of the bend lines (``instructions:``) in which every line says its angle, its inner radius and which way it goes. Both questions are asked every time, so one run says everything that is wrong.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part made by any other method.

When it fails
^^^^^^^^^^^^^

* ``The sheet metal declaration states no 'source'`` (or ``'instructions'``): name the flat blank and the sketch of the bend lines.
* ``... is not flat on the bottom`` (or ``top``): ``source:`` has to be the flat blank, not the bent part.
* ``... draws no bend lines``: the sketch has to draw each bend as a line; a layer can be picked with parameters (``bends;include=BEND_UP,BEND_DOWN``).
* ``The bend drawn by the ... cannot be made: ...``: annotate the line with an ``angle`` above 0 and below 360 degrees, a ``radius`` above 0 (a bend, not a fold), and a ``direction`` of ``up`` or ``down``.

.. _test-manufacturability-laser:

``manufacturability-laser``: Laser: faces along or across the beam
------------------------------------------------------------------

**Applies to** a part made by ``method: subtractive`` that names a ``laser:`` machine. ``pc qual test -f manufacturability-laser <object>`` runs it alone.

Whether a laser cutting along the tool axis can make the part: every face has to be either a wall along the axis or a face across it, and there has to be a wall to cut. A laser cuts straight through, so a chamfer, a taper or a fillet that is neither is not something it can make. Thickness, material and power are not checked.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, a part made by another method, and a subtractive part that names no ``laser:`` machine - a part that names no machine at all is taken to be milled.

When it fails
^^^^^^^^^^^^^

* ``A laser cutting along ... cannot make it: N of its faces are neither along ... nor across it``: remove the faces at an angle (the worst is named), or set ``toolAxis:`` to the direction the beam really goes.
* ``It has no wall along ... for a laser to cut``: the axis is wrong, or the part is not something a laser makes.

Settings
^^^^^^^^

``manufacturing: laser:`` - ``toolAxis:`` (or ``along:``, default ``-Z``) and the job keys (``kerf``, ``power``, ``feed``, ``direction``, ``implementation``).

.. _test-manufacturability-drill:

``manufacturability-drill``: Drill: round holes along the axis
--------------------------------------------------------------

**Applies to** a part made by ``method: subtractive`` that names a ``drill:`` machine. ``pc qual test -f manufacturability-drill <object>`` runs it alone.

Whether a drill working along the tool axis can make what is taken away: every wall has to be along the axis and round. Measured on the material removed from the stock when ``source:`` names one, and on the part itself otherwise.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, a part made by another method, and a subtractive part that names no ``drill:`` machine.

When it fails
^^^^^^^^^^^^^

* ``There is no hole along ... for a drill to make``: the axis is wrong, or there is nothing to drill.
* ``A drill only makes round holes, and N of the M walls along ... are not round``: make the holes round, or cut the other shapes another way. When the stock is not named, the part's own outline counts as drilled: name it with ``source:``.
* ``A drill working along ... cannot make it``: some walls are not along the axis; check ``toolAxis:``.

Settings
^^^^^^^^

``manufacturing: drill:`` - ``toolAxis:`` (or ``along:``), and the job keys (``diameter``, ``peck``, ``plunge``, ``speed``, ``safe_z``); ``manufacturing: source:``.

.. _test-manufacturability-cut:

``manufacturability-cut``: Cut: the cuts make the part
------------------------------------------------------

**Applies to** a part made by ``method: subtractive`` that names a ``cut:`` machine. ``pc qual test -f manufacturability-cut <object>`` runs it alone.

Whether cutting the stock where the part says gives the part: each declared cut is a plane, the stock is cut at every one, and what is left has to be the part. No cut may take nothing off.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, a part made by another method, and a subtractive part that names no ``cut:`` machine. A part that names no stock passes here, since ``manufacturability-subtractive`` already says so.

When it fails
^^^^^^^^^^^^^

* ``Cut #N (...) takes nothing off the stock``: the length is longer than the stock, or the axis points away from it.
* ``Cutting the stock '...' at ... does not make it: ...``: the cuts leave too much or too little; correct the lengths or the axes.

Settings
^^^^^^^^

``manufacturing: cut:`` - ``toolAxis:`` (or ``along:``) and ``cuts:``, each a ``length`` and an optional axis of its own.

.. _test-materialize:

``materialize``: Made as it says it is
--------------------------------------

**Applies to** a part with ``manufacturing: method: additive``, ``subtractive`` or ``forming`` that names a ``source:`` and has a geometry of its own. ``pc qual test -f materialize <object>`` runs it alone.

Whether a part is what its machine makes by following its instructions: the print its design's route deposits, what a router, a laser, a drill or a saw leaves of its stock, what a mold gives back of its cavity. ``pc cam --materialize`` writes that into the part's own file; this asks whether the file - or a model somebody drew, or an as-printed scan - still is it. Compared by volume and extent, within the part's tolerance; a print may also match its outside (its sections stacked up), which is what a part modelled solid is. A cut part or a molding that is the right size is compared by shape as well, since a hole moved across a plate changes neither: what either has that the other has not may be no deeper than the tolerance anywhere.

A part that names several machines is held to what each of them makes, since each is a claim that it could be made that way.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part; a part made some other way or naming nothing it is made from; and a part with no geometry of its own - no ``type:``, no file yet - which \*is\* what its machine makes. Nor a cut part that names no machine and no job, which no machine makes anything of; or a router, a laser or a drill cutting a part along its own geometry (no ``instructions:``), which is then the design the machine follows rather than a claim about what it leaves - a pocket leaves the stock with the part taken out of it, and a profile leaves the part less what a 2.5-axis route cannot cut, which ``pc cam`` warns about as it routes it.

When it fails
^^^^^^^^^^^^^

* ``It is not the size its machine makes it`` / ``It is not what its machine makes`` / ``It is not the shape its machine makes``: the file is from other settings, another design or another stock. The last says where the first difference found is, and how deep. Run ``pc cam --materialize`` to write what the machine makes now, or fix the manufacturing settings.
* ``It could not be compared with what its machine makes``: the boolean between the two failed; the sentence says why.
* ``What its machine makes could not be worked out``: see ``pc cam`` for the route; the sentence says why.

Settings
^^^^^^^^

``manufacturing:`` - ``source:``, ``instructions:`` and the machine's subsection; the part's ``tolerance``.

.. _test-connect:

``connect``: Connection instructions
------------------------------------

**Applies to** assemblies and scenes. ``pc qual test -f connect <object>`` runs it alone.

Whether the assembly's connection instructions can be followed as written: whether anything had to be bent to put it together - a ``how:`` whose minimum is above its maximum, two interfaces that disagree about the thread they share and neither cuts its own, a motion or a physics the joined ends contradict, a joint named twice, a chain that closes on itself. An assembly that says nothing about how its items go on has nothing to contradict, and passes.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but an assembly or a scene.

When it fails
^^^^^^^^^^^^^

Each failure is ``<link>: <what had to be repaired>``. Fix the declaration it names: the ``how:`` of that link, the interfaces or the mating it joins, or the joint. The list of what is reported is in "Testing the instructions" of the assembly documentation.

.. _test-connectivity:

``connectivity``: Everything is held in place
---------------------------------------------

**Applies to** assemblies and scenes. ``pc qual test -f connectivity <object>`` runs it alone.

Whether everything an assembly places is placed once, on a port that takes it, and held there. Three mistakes that render perfectly:

* the same part twice in the same place;
* two items connected to one port, when its interface does not say ``multiConnect: true``;
* an item placed by coordinates (``location:``) among items that connect, which says where it ends up but not what holds it there.

An assembly that is to be made (``manufacturable``) is held to more: no item may be placed by coordinates, and every item after the first has to connect to something.

An assembly bought whole (one declaring ``vendor`` and ``sku``) is its vendor's to put together: the coordinates in its file draw it, so nothing in it has to connect to anything, and an assembly holding it does not look inside it for that. The same part twice in one place, and two items on one port, are still reported.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but an assembly or a scene.

When it fails
^^^^^^^^^^^^^

* ``'a' and 'b' are the same part in the same place``: remove one, or move it.
* ``'a' and 'b' are both connected to '...' of '...'``: connect one of them elsewhere, or say ``multiConnect: true`` on the interface if the port does take several.
* ``'...' is placed by coordinates ...``: replace its ``location:`` with a ``connect:`` to what holds it.

Settings
^^^^^^^^

On the assembly, under ``qual: basic: connectivity:``: ``allowDuplicates: true`` to allow the same part twice in one place, and ``requireAnchored: false`` to allow items placed by coordinates.

.. _test-requirements:

``requirements``: Meets its requirements
----------------------------------------

**Applies to** objects whose ``requirements:`` require ports, interfaces, physical properties or a match with another object. ``pc qual test -f requirements <object>`` runs it alone.

Whether the model is what its ``requirements:`` say it has to be, as far as that can be measured: each required port is there, facing where it has to; each required interface is implemented, its instances where they have to be; and each required physical property - its mass, its centre of mass, its inertia, its friction - has a value that meets the requirement; and its volume, its displacement and its mass are within the percentage ``match:`` allows of each object it names - the numbers ``pc compare <that object> <this one>`` reports. Asked again every time, never read from the cache.

The ``features:`` are sentences rather than measurements, and are judged by the ``/pc:validate`` agent skill. What this check asks of them is only that a ``qual: sim:`` entry or an analysis scenario naming one (``feature:``) names one that is declared.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

An object that requires no port, interface, physical property, match with another object or ``has_`` fact (``has_color``, ``has_material``, ``has_finish``, ``has_weight``), and whose simulations and analysis scenarios name no feature.

When it fails
^^^^^^^^^^^^^

Each failure is ``<section>: <name>: <required>: <found>`` - what was asked for and what is there instead.

* A port or an interface instance that is missing, or faces the wrong way: move it in the model, or correct the requirement if the requirement is what is wrong.
* ``not known: ...``: PartCAD could not find out the value - a mass with no density to work it out from. State the value in a ``physics:`` section, or give the part a ``material:`` with a density. "Not known" is not "met".
* ``match: <amount> of <object>: within N%: ... more than N%``: the volume, the displacement or the mass is further from the other object's than the requirement allows. Run ``pc compare --displacement <object> <this one>`` for the whole comparison, and change the model or the limit, whichever is wrong.
* ``unreadable``: the requirement itself cannot be read; the detail says why.

.. _test-cmf:

``cmf``: Colour, material and finish are specified
--------------------------------------------------

**Applies to** parts and assemblies that are to be made. ``pc qual test -f cmf <object>`` runs it alone.

Whether what is to be made says what it is made of and what it looks like: for a part, a material on every solid and a colour on every face - the colour its material claims counts - each a declaration that claims it can be had (``manufacturable: true``), and a finish that is one too where a finish is stated (none stated is as produced). Where each comes from - the part's source, its ``color``, ``material`` and ``finish`` parameters - is in "CMF" of the configuration documentation.

An assembly that sets CMF itself - its own CMF parameters, a link's ``params:`` naming a colour, a material or a finish, a ``properties: color:`` - is drawing what it holds rather than specifying it, and is manufacturable only if it is bought whole: if it declares ``vendor`` and ``sku``. An assembly bought whole is judged by its own CMF, and nothing inside it is.

It warns rather than fails, unless the object says ``qual: basic: cmf: require: true``, or its package says ``cmf: require: true``.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

A sketch; an object that is not to be made (``manufacturable: false``); a part that is bought (``vendor`` and ``sku``), in whatever its vendor sells it in.

When it fails
^^^^^^^^^^^^^

* ``no colour on N face(s)`` or ``no material on N solid(s)``: state the missing component as the part's ``color`` or ``material`` parameter, or in its source.
* ``the color '...' is display-only``: name a colour declaration that claims it can be had, instead of an ``rgba`` or a ``manufacturable: false`` one.
* ``it sets CMF itself (...)``: declare the variant as a part - an ``enrich`` that fixes ``color`` - and link that, or declare ``vendor`` and ``sku`` on the assembly if it is bought as it is.

Settings
^^^^^^^^

``require: true`` to fail on what it finds rather than warn: on the object, as ``qual: basic: cmf: require: true``, and on its package, for every object of it, as ``cmf: require: true``.

.. _test-degenerate:

``degenerate``: Has size in every direction
-------------------------------------------

**Applies to** parts. ``pc qual test -f degenerate <object>`` runs it alone.

Whether a part has size in every direction. A part that built as a flat disc or an empty box - a brick whose subfile could not be fetched, a script that returned the wrong thing - renders, exports and measures, and is not the part that was meant. Read from the box measured when the part was built, so it costs next to nothing.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

A sketch, which is flat by definition, and an assembly or a scene, which is checked through its parts.

When it fails
^^^^^^^^^^^^^

* ``The shape built but occupies no space at all``: nothing came out of the build but an empty shape; find the geometry that went missing.
* ``The shape is flat in ...``: it is less than a thousandth of a millimetre thick in one direction - a missing extrusion, a missing file, a surface where a solid was meant.

A part that has size but has pieces that do not - a sliver of a face, an edge of no length - passes this and is shown those pieces by ``defects``. This one stays about the whole part, in words: a box that is flat has nothing in it to point at.

.. _test-shell:

``shell``: A body, not a skin
-----------------------------

**Applies to** parts. ``pc qual test -f shell <object>`` runs it alone.

Whether a part is a body rather than a skin: a set of faces with nothing said about which side of them is material renders and exports like the part that was meant, while every boolean against it comes back with no solid in it - so interference, CAM, FEA and any mass computed from it are wrong. Read straight out of the geometry the part has already produced, so it costs nothing.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

A sketch, which is not a body, and an assembly or a scene, which is checked through its parts.

When it fails
^^^^^^^^^^^^^

``The shape is a skin rather than a body: N shell(s) that no solid bounds itself with``. A shell a script returns is closed into a solid automatically, so either those faces enclose nothing - close them - or they come from a file that states the part as a surface: export it from its tool as a solid instead.

.. _test-solidity:

``solidity``: Not inside out
----------------------------

**Applies to** parts. ``pc qual test -f solidity <object>`` runs it alone.

Whether every solid of a part has a positive volume. A solid whose faces are oriented inward measures the right size and a negative volume: it renders correctly, and every boolean against it is wrong. Asked before ``interference``, deliberately, since an inside-out part overlaps things it is nowhere near.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

A sketch, which has no solid, and an assembly or a scene, which is checked through its parts.

When it fails
^^^^^^^^^^^^^

``... a constituent solid measures ... mm^3``: negative means the faces are oriented inward - fix their winding in the source (an LDraw part, for one, has to state it); zero means the solid encloses nothing.

.. _test-validity:

``validity``: A well-formed solid
---------------------------------

**Applies to** parts. ``pc qual test -f validity <object>`` runs it alone.

Whether the geometry kernel certifies a part's solid as well formed. It reports and never fails: the parts it has the most to say about are often ones nothing is functionally wrong with. A part it reports on is one to expect trouble from in anything exacting - booleans, meshing for print, CAM - so treat a strange result from those as this rather than as the tool.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

A sketch, which is not a body, and an assembly or a scene, which is checked through its parts.

When it fails
^^^^^^^^^^^^^

It does not fail. When it says ``the geometry is a solid but not a well formed one``, look at ``defects`` in the Topology tab, which shows the faces and edges that are the reason; rebuild the part more simply where it can be - fewer tiny faces, no self-intersections - or re-export it from its source.

.. _test-cam:

``cam``: A machine route can be produced
----------------------------------------

**Applies to** parts and sketches that name a machine to be cut or printed on. ``pc qual test -f cam <object>`` runs it alone.

Whether the program a machine makes the object with can be produced: for every ``cnc:``, ``laser:``, ``drill:`` or ``fff:`` machine it names, the post-processor that machine uses writes a route, and the route is thrown away. The same code as ``pc cam``.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

An object that names no machine to be routed on - nothing under ``manufacturing:`` asks for one, or only a ``cut:`` or a ``mold:``, neither of which runs a program.

When it fails
^^^^^^^^^^^^^

* A sentence about the section: a job key it cannot read; fix it.
* ``the 'cam' implementation could not be resolved``: the implementation the machine names is not a dependency of the package, or does not declare the file type.
* ``no route was produced by ...``: the post-processor's error follows; fix the tool or the outline it names, or run ``pc cam`` to see the whole report.

It is skipped, with a warning, where the implementation cannot run on this machine: start a container runtime, or install what it needs.

.. _test-fea:

``fea``: Structural analysis (FEA)
----------------------------------

**Applies to** parts that declare an ``fea:`` section. ``pc qual test -f fea <object>`` runs it alone.

Whether a part holds up under the loads each scenario of its ``fea:`` section declares: every scenario is run by the implementation configured, and the part passes when each of them ran and found nothing - the same analyses as ``pc cae fea``, which runs one of them with ``-f <scenario>``.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part that declares no ``fea:`` section.

When it fails
^^^^^^^^^^^^^

* A sentence about a scenario (``'fea: loaded:' declares neither 'fix:' nor 'load:'``, a key it does not take): fix the scenario it names.
* ``FEA 'loaded' could not be run by ...``: the solver or the mesher is not installed, or failed; the report says which. Install it, or name another implementation.
* ``FEA 'loaded' findings: ...``: the analysis ran and found a problem - a stress, a deflection - at the place named. Change the design, or the load if the load is what is wrong.

It is skipped, with a warning, only where the implementation runs in a container and there is no container runtime here.

Settings
^^^^^^^^

``fea: <scenario>: fix:``, ``load:`` (a force; a bare number is kilograms), ``gravity:``, ``implementation:`` and ``params:``; the user setting ``caeFeaImplementation``.

.. _test-dynamic:

``dynamic``: Vibration analysis (Dynamic FEA)
---------------------------------------------

**Applies to** parts that declare a ``dynamic:`` section. ``pc qual test -f dynamic <object>`` runs it alone.

Whether a part, held as each scenario of its ``dynamic:`` section says, rings only where it may: the modal analysis of every scenario is run by the implementation configured, and the part passes when each ran and found nothing - the same analyses as ``pc cae dynamic``. A natural frequency is a property of the part and how it is held, not of what it carries, so a scenario says only where it is held.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part that declares no ``dynamic:`` section.

When it fails
^^^^^^^^^^^^^

* A sentence about a scenario (``'dynamic: bolted:' declares none of 'fix:'``, a key it does not take, such as ``load:``): fix the scenario it names.
* ``DYNAMIC 'bolted' could not be run by ...``: the solver or the mesher is not installed, or failed; the report says which. Install it, or name another implementation.
* ``DYNAMIC 'bolted' findings: ...``: the analysis ran and found a problem - a mode where the part must not ring. Change how it is held, or its stiffness or mass.

It is skipped, with a warning, only where the implementation runs in a container and there is no container runtime here.

Settings
^^^^^^^^

``dynamic: <scenario>: fix:`` (the interfaces it is held by), ``implementation:`` and ``params:``; the user setting ``caeDynamicImplementation``.

.. _test-thermal:

``thermal``: Heat transfer
--------------------------

**Applies to** parts that declare a ``thermal:`` section. ``pc qual test -f thermal <object>`` runs it alone.

Whether a part, heated and cooled as each scenario of its ``thermal:`` section says, stays as cool as it has to: every scenario is run by the implementation configured, and the part passes when each ran and found nothing - the same analyses as ``pc cae thermal``.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part that declares no ``thermal:`` section.

When it fails
^^^^^^^^^^^^^

* A sentence about a scenario (``'thermal: in-use:' declares none of 'temperature:', 'heat:', 'convection:'``, a key it does not take): fix the scenario it names.
* ``THERMAL 'in-use' could not be run by ...``: the solver or the mesher is not installed, or failed; the report says which. Install it, or name another implementation.
* ``THERMAL 'in-use' findings: ...``: the analysis ran and found a problem - a temperature the part must not reach - at the place named. Change the design, how it is cooled, or the heat if the heat is what is wrong.

It is skipped, with a warning, only where the implementation runs in a container and there is no container runtime here.

Settings
^^^^^^^^

``thermal: <scenario>: temperature:`` (held at, in Celsius), ``heat:`` (put in, in watts), ``convection:`` (a film coefficient, in W/(m^2\*K)), ``implementation:`` and ``params:``; the user setting ``caeThermalImplementation``.

.. _test-cfd:

``cfd``: Flow analysis (CFD)
----------------------------

**Applies to** parts that declare a ``cfd:`` section. ``pc qual test -f cfd <object>`` runs it alone.

Whether a part behaves in the flow each scenario of its ``cfd:`` section declares: every scenario is run by the implementation configured, and the part passes when each ran and found nothing - the same analyses as ``pc cae cfd``.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, and a part that declares no ``cfd:`` section.

When it fails
^^^^^^^^^^^^^

* A sentence about a scenario: fix the scenario it names.
* ``CFD '<scenario>' could not be run by ...``: the solver is not installed, or failed; the report says which.
* ``CFD '<scenario>' findings: ...``: the analysis ran and found a problem at the place named.

It is skipped, with a warning, only where the implementation runs in a container and there is no container runtime here.

Settings
^^^^^^^^

``cfd: <scenario>: fix:``, ``load:``, ``outlet:``, ``implementation:`` and ``params:``; the user setting ``caeCfdImplementation``.

.. _qual-topology:

Topology
========

Checks whose findings are places on the object, left behind as geometry to look at. ``pc qual test --topology`` runs these alone.

.. _test-defects:

``defects``: No badly made faces or edges
-----------------------------------------

**Applies to** parts. ``pc qual test -f defects <object>`` runs it alone.

Which faces and edges of a part are badly made, shown where they are. ``validity`` says that the geometry kernel will not certify a part, and ``degenerate`` that a part has no size in some direction; both are about the whole of it. This finds the pieces that are the reason, and leaves them behind to look at:

* \*\*free\*\* edges of a solid - an edge that bounds one face only, which is a hole in its skin (a part meshed from triangles that were never joined has hundreds);
* \*\*slivers\*\* - an edge shorter than a thousandth of a millimetre, or a face narrower than that, which a mesher chokes on and a CAM path stalls at: the ``degenerate`` question asked of each piece;
* faces and edges the kernel finds fault with on their own - a wire that crosses itself, a curve that leaves its surface - by the kernel's own name for it.

The faces and the edges (as tubes along them) are left behind in an assembly of the part and, in a sub-assembly named ``focus``, the pieces, drawn in red and orange. The IDE's Topology tab shows them with the rest of the part faded and a callout on each (\*\*Show\*\*). Like ``validity``, it reports and never fails.

A large part - a 3D print made of tens of thousands of beads, a plate drilled with thousands of holes - is checked in shards side by side, each in a sandbox of its own, as many at once as ``threadsMax`` lets PartCAD run; what it finds and shows is the same as checked in one piece. A part whose geometry is under a megabyte, compressed, is checked in one piece, as sharding would cost it more than it saves.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

A sketch, a surface by its type (a wall), a part that holds no solid (``shell`` reports that), and an assembly or a scene, which is checked through its parts.

When it fails
^^^^^^^^^^^^^

It does not fail. When it reports ``K of its N faces ... are defective``, rebuild those pieces in the part's source - join the free edges, merge or remove the slivers - or re-export it from its tool. When every face is defective, nothing is drawn: that is the whole part, and ``validity`` says the same of it.

Settings
^^^^^^^^

On the part, under ``qual: topology: defects:``: ``minLength:`` (mm, default 0.001), the length below which an edge, and the width below which a face, is a sliver.

.. _test-interference:

``interference``: Parts do not overlap
--------------------------------------

**Applies to** assemblies and scenes. ``pc qual test -f interference <object>`` runs it alone.

Whether the parts of an assembly share space. Boxes are used only to pick the pairs worth asking about; the answer comes from intersecting the two solids and measuring what they share. Each sub-assembly declared in the package answers for its own inside with its own verdict, so only what crosses its boundary is looked at here. It is the most expensive of the geometry checks.

An overlap that is meant to be there is read from the joint between the two: a port, an interface or a mating that says ``selfScrew`` (a screw cutting its own thread, a nail making its own hole), a mating that says ``snapIn`` (a pin pushed past a feature), a connection whose ``how:`` says either, and a connection's ``interferes:``, naming the further items the same act of joining drives through. Nothing is ever excused for a pair of parts by name.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but an assembly or a scene.

When it fails
^^^^^^^^^^^^^

* ``'a' and 'b' share N mm^3``: the two are in each other. Each such failure leaves an assembly to look at: the two parts where the assembly places them, and a sub-assembly named ``interference`` holding what they share, one part per volume, drawn in red. The IDE's Topology tab shows it with everything but the overlap faded (\*\*Show\*\*); ``pc ide view`` and its name (``<assembly>/interference/<a>+<b>``) shows it whole, and switching the two parts off leaves the overlap alone. Then move one of them - or, if the overlap is the joint, say so on the joint.
* ``'...' does not pass on its own``: a sub-assembly has overlaps of its own; test it.
* ``'...' names '...' in 'interferes:', which is not a link``: correct the name; it is a link of the same ``links:`` list as the connection.
* An object marked ``manufacturable: false`` (a scene, unless it says otherwise) is told what overlaps rather than failed for it.

Settings
^^^^^^^^

On the assembly, under ``qual: topology: interference:``: ``minVolume:`` (in mm^3, default 0.05), below which an overlap is taken for the arithmetic of two surfaces that touch, and ``minFraction:``, the same floor as a share of the smaller part.

.. _test-tolerance-surfaces:

``tolerance-surfaces``: Every face of a part to be made is toleranced
---------------------------------------------------------------------

**Applies to** parts that are to be made (``manufacturing:``). ``pc qual test -f tolerance-surfaces <object>`` runs it alone.

Whether every face of a part that is to be made says how precisely it has to be made. A face is covered by the part's general tolerance - its ``tolerance:``, or the ``tolerance`` parameter of a type that takes one, which is a drawing's "unless otherwise stated" - or by a dimension or a geometric tolerance of the STEP file the part is read from that refers to it. ``manufacturability`` asks only whether the part states a tolerance at all, and passes a file that tolerances some of its features; this asks which.

The faces nothing covers are counted, the largest is named, and all of them are left behind to look at: an assembly of the part and, in a sub-assembly named ``focus``, the faces themselves, drawn in red. The IDE's Topology tab shows it with the rest of the part faded and a callout on each of the largest (\*\*Show\*\*).

Only some of its faces, though. A part that tolerances nothing at all has every face untoleranced, and showing all of them singles nothing out: that part states no tolerance, which is ``manufacturability``'s finding, and this check does not apply to it.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part; a part that says ``manufacturable: false``; a part that is bought (``vendor:`` and ``sku:``) or does not say how it is made; a surface by its type (a wall); a part that states no general tolerance and whose file tolerances nothing (``manufacturability`` fails it).

When it fails
^^^^^^^^^^^^^

* ``K of its N faces have no tolerance``: the file tolerances some faces and not these, and there is no general tolerance to cover the rest. Tolerance them, or state a general tolerance for the ones that need nothing tighter.
* ``none of its N faces has a tolerance ... that is all of it``: the part's general tolerance is set not to count (``general: false``) and its file tolerances nothing, or nothing of the size counted. Said in words, with nothing drawn.

Settings
^^^^^^^^

On the part, under ``qual: topology: tolerance-surfaces:``: ``minArea:`` (mm^2), below which a face - a fillet, a chamfer - is not reported, and ``general: false``, which stops a general tolerance from covering the faces, for a part every face of which has to be toleranced on its own.

.. _test-tolerance-edges:

``tolerance-edges``: Every edge of a part to be made is toleranced
------------------------------------------------------------------

**Applies to** parts that are to be made (``manufacturing:``). ``pc qual test -f tolerance-edges <object>`` runs it alone.

The same question as ``tolerance-surfaces``, of every edge: an edge is covered by the part's general tolerance, by a dimension or a tolerance of its STEP file that refers to it, or by both of the faces it is where they meet being covered. A seam - the edge a round surface is cut along to be described - is not a feature of the part and is not counted.

The edges nothing covers are left behind as tubes along them, drawn in orange, in the same kind of assembly ``tolerance-surfaces`` leaves, and shown the same way.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

As for ``tolerance-surfaces``.

When it fails
^^^^^^^^^^^^^

* ``K of its N edges have no tolerance``, ``none of its N edges has a tolerance ... that is all of it``: as for ``tolerance-surfaces`` - a general tolerance covers every edge, and an edge between two toleranced faces is covered by them.

Settings
^^^^^^^^

On the part, under ``qual: topology: tolerance-edges:``: ``minLength:`` (mm), below which an edge is not reported, and ``general: false``, as for ``tolerance-surfaces``.

.. _qual-sim:

Simulation
==========

The simulations an object declares under ``qual: sim:``, run and judged. ``pc qual test --simulation`` runs this alone.

.. _test-sim:

``sim``: Does what its simulations say
--------------------------------------

**Applies to** parts, assemblies and scenes that declare simulations (``qual: sim:``). ``pc qual test -f sim <object>`` runs it alone.

Whether the object does what its simulations say it does: each simulation declared under ``qual: sim:`` is run - the object placed in its scene and handed to the simulation plugin its ``path:`` names - and its ``validation:`` condition has to hold over what came back. ``pc qual test --simulation`` runs these alone, and then also prints everything the plugin reported (``--json``). It is the most expensive question asked, and is asked last; the IDE plays each run in the Simulation tab.

When it does not apply
^^^^^^^^^^^^^^^^^^^^^^

Anything but a part, an assembly or a scene, and one that declares no simulation.

When it fails
^^^^^^^^^^^^^

* ``... ran, and its 'validation' does not hold``: the object did not behave as claimed. Run ``pc qual test --simulation --json`` to see ``before`` and ``after``, then change the design, or the condition if the condition is what is wrong.
* ``... could not be run``: the plugin or the scene the entry names is not found, or the simulator failed; the report says which.
* ``... states no 'validation'``: asked about by name, an entry with no condition fails; add one over ``before`` and ``after``. Walked to as part of a package, it is skipped instead.

It is skipped, with a warning, where the simulator runs in a container and there is no container runtime here.

Settings
^^^^^^^^

``qual: sim: <name>:`` - ``path:`` (the plugin), ``scene:``, ``offset:``, ``validation:``, ``params:``, and ``feature:``, the feature of the requirements it demonstrates.

.. _qual-other:

Other
=====

Checks of other tools' own, which plugins supply. None is built in.

.. END GENERATED FROM partcad.qual.catalog

Agent skills
============

``/pc:validate``
  Runs ``pc qual test`` as the first thing it does, and then goes beyond it: it runs
  every simulation and every analysis scenario, renders the object from every
  angle that matters with its ports and interfaces drawn, reads the bill of
  materials and the assembly instructions of an assembly, and gives every
  requirement a verdict -- met, not met, or "cannot tell" -- with the evidence
  named. The ``features:`` half of a requirement is prose, which no check here
  can measure, and it is judged there and nowhere else.

``/pc:sim-assembly-fea``
  Produces the ``fea:`` scenario that the ``fea`` check below then holds the
  part to, out of what a simulation of its assembly measured.

Every skill runs these same commands, through the same cache, so a verdict an
agent reports is a verdict you can reproduce by hand.
