############
Output files
############

.. _output-files:

============
Output files
============

``pc export`` writes 3D and CAD files; ``pc render`` writes 2D projections. Both
are configured by a section of ``partcad.yaml`` named after the command --
``export:`` and ``render:`` -- with one subsection per output file type:

.. code-block:: yaml

  export:
    <file type>:
      path: <(optional) the script that writes the file>
      package: <(optional) the package that script belongs to>
      # The environment the script runs in. Read from the package that ships
      # the script and from nowhere else, so these two say something only in
      # the package that also declares "path".
      pythonRequirements: # (optional) what that script's sandbox needs
        - <requirement>
      pythonVersion: <(optional) the sandbox interpreter to run it on>
      extension: <(optional) the extension used when the file name is derived>
      prefix: <(optional) where the file goes, relative to the package>
      exclude: <(optional) kinds of object not to write this type for>
      reproducible: <(optional) true to require the same bytes every time>
      <parameter name>: <value> # anything else is an export parameter

  render:
    <file type>:
      ... # the same fields, for the 2D projections

The two sections behave identically. Which one a file type belongs to is
decided by whichever built-in package implements it (see `Built-in
implementations`_) -- ``step`` is an ``export:`` type wherever it is written
down, ``svg`` is a ``render:`` one. For a file type no built-in package
implements, the section it is declared in is what decides: declare a type of
your own under ``export:`` and it is an export type, under ``render:`` and it is
a render type.

Whichever section owns a file type, the other one is read first and acts as a
fallback, so the owning section always wins where both set the same field.

For an ``export:`` type the fallback is history: a package that configured its
STEP or STL output under ``render:`` before ``export:`` existed keeps working.

For a ``render:`` type the fallback is what an export implementation *is*. An
export file is one a CAD tool can open as a part or a sketch, which is a
stricter thing to be than an output file in general -- so it also serves
wherever any output file would do, and a render request for a file type only
``export:`` implements uses that implementation.

Note that neither fallback has anything to do with which command was typed.
``pc export`` and ``pc render`` differ in their defaults, not in the section
they read: a file type declared only under ``render:`` is produced by
``pc export -t <type>`` just as well, because the section follows the
declaration and not the command.

What the two sections do say is what a file type *is*, and that is worth
getting right when publishing a package. Declare a type under ``export:`` and
you are promising geometry another tool can go on working with; declare it
under ``render:`` and you are promising an output file, nothing more. A drawing,
a picture or a report is the latter -- so declare it under ``render:``, where it
stays reachable from both commands, rather than under ``export:``, where it
would promise a part it cannot deliver.

The short form ``<file type>: <path>`` is the same as ``prefix: <path>``.

Where the file goes
-------------------

``prefix`` is the directory the file goes in, relative to the output directory
(``-O``) or, failing that, to the package. A ``prefix`` that carries an
extension names the file itself, which is the one way to give an object's output
a name of its own. Otherwise the file is named after the object, with the
extension the file type declares.

An object whose name carries a ``/`` is written into a sub-directory of that
name, and the directories are created on the way. A package may declare an
object that way itself, and the objects another file materializes are named that
way whether it did or not -- a STEP assembly's components are the parts
``<assembly>/<component>``, a URDF's links ``<assembly>/<link>``:

.. code-block:: shell

  pc export -t step -O ./ //pub/examples/partcad/produce_assembly_urdf:robot/wrist
  # ./robot/wrist.step

The separator in a *name* is always ``/``, whichever operating system reads it,
so the same command produces the same tree on Linux, macOS and Windows.

Every directory an output file needs is created on the way to writing it: the
sub-directories a name with a ``/`` in it asks for, and the directory around
them that ``-O``, ``prefix`` or ``output_dir`` named and nobody has made. There
is nothing to ask for -- the ``-p``/``--create-dirs`` flag that used to draw a
line between those two halves of one path is gone, and both halves are made.

Export parameters
-----------------

Every field that is not one of those listed above is a parameter of that file
type, handed to whatever implements it. Which parameters exist is therefore up
to the implementation, not to PartCAD. For example, the built-in STEP
implementation accepts ``comment``, which it places into the STEP file's
``FILE_DESCRIPTION`` header entity:

.. code-block:: yaml

  export:
    step:
      comment: Produced by ACME Corp. Not for manufacturing.

Every STEP file the package produces -- for any part or assembly in it -- then
carries that text.

Parameters may be declared per package, as above, or per object, in which case
the object's value wins:

.. code-block:: yaml

  parts:
    bracket:
      type: cadquery
      export:
        step:
          comment: Revision C.

A parameter can also be given for one command instead of written down. The two
that aim a 2D projection -- ``viewport_origin``, which is where the shape is
looked at from, and ``viewport_up``, which way is up in the picture -- are
``pc render --viewport-origin``/``--viewport-up``, with ``--view`` naming the
common directions (see :doc:`cli`). Passed that way they layer on top of
everything below, package and object alike, for that run only.

Three names are not entirely the package's own.

``decode`` is not a parameter at all. It is one of the fields PartCAD reads
itself -- it says whether the sandbox rebuilds the shape and assembly envelopes
into live geometry before the implementation sees them (see ``urdf`` under
`Built-in implementations`_) -- so no package can declare an export parameter
named ``decode``: a ``decode:`` in a file type's configuration is always that
flag.

``properties`` is the other way round, and it is a parameter -- with a caveat. A
file type that declares ``properties: true`` is handed, in place of the flag, an
index of what the shapes being written declare about themselves: their
``physics``, ``material`` and ``color``, keyed by the full ``<package>:<name>``
of each shape, so an implementation given a whole assembly tree can look up the
properties belonging to each node of it. Each shape's ``physics`` is complete:
what it states, what its material lends, and the ``mass``, ``centerOfMass`` and
``inertia`` its solid comes to at its ``density`` (see :ref:`properties`), so an
implementation writes those and works none of them out. A body made of several
shapes is the one thing left to it, and ``mass_properties.of_body()`` in
PartCAD's ``wrappers/`` directory -- on the path of every implementation -- adds
them up. Only shapes that declare something, or have a mass worked out for
them, appear.

A part that states no density and is made of nothing that does is weighed at
the file type's ``density`` parameter, in kg/m³, or at 2700 kg/m³ (aluminium)
where the file type declares none. That makes ``density``, after ``properties``
itself, the one other parameter PartCAD reads on an implementation's behalf
when ``properties: true`` is declared; it is still passed through as well.

.. code-block:: yaml

  export:
    urdf:
      properties: true

It is opt-in because building the index instantiates the whole assembly tree,
which defeats the shape cache for that subtree: an assembly whose geometry could
have been served from the cache has to be built anyway, so that its children
exist to be walked. An implementation with no use for the properties should not
pay for that. ``urdf`` is the one built-in file type that asks.

The caveat is that ``properties``, unlike ``decode``, is *not* a reserved field
name, and PartCAD intercepts it by value rather than by declaration: a package
that declares an ordinary export parameter of its own named ``properties`` and
gives it the value ``true`` will find that value replaced by the index before
its implementation sees it. Any other value is passed through untouched, but the
name is best avoided for anything else.

.. _reproducible:

``reproducible`` is the third, and it is a field of the protocol rather than any
one format's parameter. It is a boolean, it defaults to ``false``, and it says
whether this file has to come out **byte-for-byte the same every time it is
written**, from the same object:

.. code-block:: yaml

  render:
    svg:
      reproducible: true

Unlike every other parameter, it is handed to the implementation whether or not
anybody declared it -- so an implementation reads ``request["reproducible"]``
without first checking that the key is there, and means by it what every other
implementation means. That is the whole point of it being here rather than in
each format's own list of options: a package that publishes a ``render:``
implementation of its own writes ``reproducible`` and it already means this.

What it does depends on the file type, and on four of them it does something
today:

``svg``, ``png``, ``jpeg``
  The projection goes through OpenCASCADE's **exact** hidden-line algorithm
  rather than the polygonal one. The exact algorithm works from the surfaces;
  the polygonal one works from a triangulation, which is floating point all the
  way down, so the same shape meshed to the same deflection comes out with a
  slightly different silhouette on a different architecture.

  Every number written into the drawing is also rounded to the ``precision`` the
  file type claims (ten decimal places by default), and a negative zero is
  written as zero. Below that precision what is in the file is the last bit of
  an arithmetic rather than a measurement -- a stroke width that differs in its
  sixteenth digit, an arc rotated by half a femtodegree -- and it is a diff
  every time the drawing is produced somewhere new.

  For ``png`` and ``jpeg`` that settles the picture and not the encoding -- the
  bytes below the projection are svglib's, reportlab's and Pillow's.

``dxf``
  The same, plus fixed header metadata: a DXF is otherwise stamped on every save
  with the time it was written and a fresh pair of GUIDs, and ezdxf derives the
  order of its ``CLASSES`` section from a ``set``, so it emits differently per
  process.

It is off by default because it is not free. The exact projection is the slower
of the two by a wide margin on anything large, and it is the one that can take
the sandbox down: every released OpenCASCADE reads past the end of an allocation
in the rejection table that algorithm sorts its edge crossings in
(`Open-Cascade-SAS/OCCT#1546
<https://github.com/Open-Cascade-SAS/OCCT/issues/1546>`_), which is a coin flip
on an assembly with enough edges. A picture produced to be looked at should be
the fastest correct one; a drawing that is *kept*, so that a diff answers
whether it changed, is the case that says so. Every image under ``examples/`` in
the PartCAD repository sets it.

The rest of the built-in file types accept it and write the same bytes either
way. They declare it all the same, so that an implementation which starts
reading it does not also have to start receiving it.

What it is not is a promise that two machines produce one file. It removes
everything PartCAD chooses -- which algorithm, how a number is written, the
clock, the GUIDs, the iteration order of a ``set`` -- and what is left is the
CAD kernel's own arithmetic. Two platforms that disagree about a transcendental
function in the last bit can still find one intersection more than each other
along a curved silhouette, and no amount of rounding makes those two drawings
the same file. So two renders on one machine are the same file, and two
machines agree on everything but the hardest subjects. That is why PartCAD's own
``Examples (PartCAD)`` job compares the checked-in drawings on one cell of its
matrix rather than on all of them.

Custom implementations
----------------------

Declaring ``path`` for a file type replaces the implementation itself with a
script the package supplies. This is the same mechanism as a ``partType``
wrapper: the script runs inside a PartCAD sandbox, so it may import OCP,
build123d or CadQuery, and it is executed with two globals available --

- ``request`` -- the shape in ``request["wrapped"]``, every export parameter the
  configuration resolved to, and ``shape_name``, ``shape_kind`` and
  ``shape_type`` describing the object being written
- ``path`` -- the absolute path of the file to write

-- and reports what happened either by setting a global ``output``:

.. code-block:: python

  output = {"success": True}
  # or
  output = {"success": False, "exception": "..."}

or by defining a function that returns the same thing, which is what lets one
implementation reuse another:

.. code-block:: python

  def process(path, request):
      ...
      return {"success": True, "exception": None}

.. code-block:: yaml

  export:
    stl:
      path: my_stl_exporter.py
      pythonRequirements:
        - cadquery-ocp==7.9.3.1.1
      comment: Produced by ACME Corp.

``path`` is resolved relative to the package that declared it. A file type that
no built-in package implements may be declared this way too, and is then
nameable with ``pc export -t`` / ``pc render -t`` like any other.

See ``examples/feature_export_custom`` for both halves of this.

Using another package's implementation
--------------------------------------

``pc export -e <package>`` (and ``pc render -e <package>``) reads the
``export:``/``render:`` sections of a further package on top of the built-in
ones, so an implementation declared in one package can be applied to the objects
of another without that package knowing about it:

.. code-block:: shell

  pc export -t stl -e //acme/exporters --package //some/other/package -O ./ bracket

That is one command's worth of it. To have a package's own output written that
way every time, declare the file type and say where the implementation lives:
``package`` names the package, ``path`` the script inside it. The implementing
package is fetched like any other dependency, and its ``pythonRequirements`` are
installed into the sandbox before its implementation runs, so nothing has to be
installed by hand:

.. code-block:: yaml

  dependencies:
    pub:
      onlyInRoot: true
      type: git
      url: https://github.com/partcad/partcad-index.git

  render:
    pdf:
      package: //pub/feature/render/draftwright
      path: render_draftwright.py
      title: Mounting Plate  # a parameter of that implementation

``examples/feature_render_custom`` is exactly this: three file types drawn by an
implementation published in the public index.

The sandbox comes with the implementation rather than from the package asking
for the file. Both ``pythonVersion`` and ``pythonRequirements`` are read from
the implementing package -- from the file type as *that* package declares it, or
from the package itself -- and from nowhere else. It could not be otherwise: the
caller may be a package of STEP files with no Python in it at all, and it has
never heard of what that script imports. Where the implementing package declares
no interpreter, it is a fixed default rather than whichever one PartCAD itself is
running on, which would otherwise scatter the sandbox across versions depending
on how PartCAD was installed.

Both fields still parse anywhere -- every field of a file type layers the same
way -- so setting them on a file type whose implementation lives elsewhere is
not an error. It simply describes nothing: the environment being described
belongs to the package that wrote the script.

Bringing dependencies pip cannot install
----------------------------------------

A Python sandbox can bring whatever pip can install, which is not everything. A
native executable is not a Python package at all, and some Python packages
publish no wheel for some platforms -- gmsh publishes none for 64-bit ARM Linux
and no source distribution either. A package that needs one of those names an
image of its own, and PartCAD builds the ``docker`` sandbox from that image
instead of from its own:

.. code-block:: yaml

  dockerImage: ghcr.io/example/solver:1a2b3c4d5e6f

``dockerImage`` is read wherever ``pythonVersion`` is -- on the package, on a
part or sketch that runs a script, on a provider, and on a file type in
``export:``, ``render:``, ``cam:`` or ``cae:``:

.. code-block:: yaml

  cae:
    fea:
      path: solve_fea.py
      extension: glb
      dockerImage: ghcr.io/example/solver:1a2b3c4d5e6f

Like ``pythonVersion`` and ``pythonRequirements``, it is read from the
*implementing* package and from nowhere else, for the same reason: which
environment a script needs is known only to whoever wrote it.

The image is a **runtime, not a delivery mechanism**. PartCAD mounts the package
tree into it at run time, so a user who fetches a newer version of your package
gets that version and not one baked into an image months ago. An image that
carries the package's own code will be serving stale code the first time anybody
updates.

**Declaring an image does not excuse declaring requirements.** A
``dockerImage`` says where this runs *best*; it does not say where this runs at
all. Every package that names one still declares the complete
``pythonRequirements`` (or a ``requirements.txt``), so that the same package
works in a ``conda`` or ``venv`` sandbox on a host that already has the
non-Python pieces installed -- a workstation with ``ccx`` on its ``PATH``, a CI
runner where the job installed them. What the image is for is everything pip
cannot supply. What happens where neither is satisfied is an ordinary failure,
reported with whatever the implementation said was missing.

The same holds where the image simply cannot be pulled -- an offline machine, a
firewall, a registry that has not been logged in to. PartCAD says so once and
falls back to its own base image, because "runs best here" is not "runs only
here"; the package's requirements are then the whole of what it gets, which is
exactly the case the paragraph above is about.

**The declared image is part of what a shape is cached under.** An image is
named precisely for what pip cannot install, so two images carrying the same
interpreter and the same wheels are still two different native stacks. Changing
``dockerImage`` therefore rebuilds the shapes that were produced under the old
one rather than handing back what it built.

What is keyed is the *declaration*, never the image a sandbox ended up running.
Every sandbox type is expected to produce the same result from the same
declaration, so a shape -- or an analysis, a route or a simulation of it -- that
a ``conda`` sandbox produced is found again from ``docker``, ``remote`` or
``venv``, and the other way round. Falling back to PartCAD's own image, or
installing the requirements on a machine with no container runtime, keys
exactly as the image it stands in for; PartCAD's own base image, whose tag
carries the release and the architecture, is never in a key at all. A package
that declares no image keys exactly as it did before there was such a thing as
an image.

.. _docker-image-architecture:

Architecture, and the name PartCAD actually pulls
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PartCAD appends the architecture of the machine to the name before pulling it,
so the name above is pulled as::

    ghcr.io/example/solver:1a2b3c4d5e6f-arm64

and falls back to the bare ``ghcr.io/example/solver:1a2b3c4d5e6f`` when there is
no such tag. One line in ``partcad.yaml`` therefore covers every architecture
your image is built for, and adding one later is a new tag rather than an edit
to every package that uses it.

Build the suffixed tags. The bare name exists so that a first experiment works
before its author has heard of any of this, and a package that only has one is
a package that works on the machine it was written on -- which is why the public
index does not accept them.

Pinning
^^^^^^^

Pin an **immutable** tag, whose content cannot change under it -- a digest, or a
tag derived from a hash of what the image was built from. An image that changes
under a fixed name changes what a part renders as, with nothing in the package
to say so, and nothing checked into a repository can be trusted to still mean
what it did.

Test against a moving one as well. A package whose continuous integration also
runs against, say, ``:latest`` finds out that a rebuilt base image broke it from
its own test run, rather than from a user's bug report after it bumps the pin.
The two uses do not conflict: what is pinned is what users get, what moves is
what the maintainer watches. Anything whose output is compared byte for byte --
the images checked in under ``examples/`` -- pins the immutable tag, or the
comparison fails for changes nobody made.

Building on PartCAD's images
^^^^^^^^^^^^^^^^^^^^^^^^^^^^

PartCAD publishes a base image per supported Python version and architecture,
carrying the interpreter and the service that runs scripts inside it. Build on
one of those, add what pip cannot install, and the result is an image PartCAD
knows how to talk to:

.. code-block:: dockerfile

  FROM ghcr.io/partcad/partcad-container-python:0.8.58-py3.11-arm64

  RUN apt-get update \
    && apt-get install --yes --no-install-recommends calculix-ccx \
    && rm -rf /var/lib/apt/lists/*

``tools/containers/README.md`` in the ``partcad`` repository states what the
base image guarantees, what a derived image may change, and how to check that
yours still conforms. Carry the ``partcad.*`` labels it documents: they are what
``pc system prune`` recognises, and an image without them is one PartCAD will
leave behind when it cleans up after itself.

What it costs
^^^^^^^^^^^^^

A container runtime, and the size of the image. On a machine with neither a
container runtime nor the dependencies installed natively, the package cannot
run -- and says which of the two would fix it.

Built-in implementations
------------------------

The export and render formats PartCAD ships are not special-cased anywhere: they
are declared in exactly the form above by two packages that live inside the
``partcad`` installation and that every context can reach, ``//builtin/export``
and ``//builtin/render``. They are the bottom layer of the configuration, so a
package that sets a single parameter keeps the built-in implementation for
everything else, and a package that sets ``path`` replaces it.

Two of the other sections ship one the same way: ``//builtin/cam`` declares the
``gcode`` file type ``pc cam`` writes (see :ref:`pc cam <cam>`), and
``//builtin/open`` declares the applications ``pc ide open`` starts. ``cae:`` is the
one that ships nothing, because PartCAD implements no solver.

``//builtin/export`` implements ``step``, ``brep``, ``stl``, ``3mf``, ``obj``,
``gltf``, ``iges``, ``threejs`` and ``urdf``. ``//builtin/render`` implements
``svg``, ``png``, ``jpeg`` and ``dxf``. Reading their ``partcad.yaml`` is the most direct
way to see what parameters each file type takes and what a package's own
implementation should look like.

It carries neither ``world`` nor ``mjcf``: an engine's own scene format belongs
to that engine's plugin package, beside the reader and the simulator that share
its knowledge of the format. Write ``sim-gazebo:world`` and ``sim-mujoco:mjcf``
(see `Naming a file type elsewhere`_), which resolve through the plugin.

Naming a file type elsewhere
----------------------------

A file type is ordinarily a bare name -- ``step``, ``png`` -- and every package
with an opinion about it is layered on top of the built-in one. It may also be
written as a full resource path, which names the package the implementation
lives in:

.. code-block:: shell

  pc export -t sim-gazebo:world -S warehouse

.. code-block:: yaml

  scenes:
    warehouse:
      type: sim-gazebo:world     # the same spelling, for the reader
      path: warehouse.world

That is the spelling every other section resolved this way already takes --
``import:``, ``simulation:``, ``pc cae --implementation`` -- and it is here for
the same reason: a format PartCAD ships no implementation of has no other way to
be reached. Nothing in ``//builtin/export`` is going to write MJCF or SDFormat,
so ``pc export -t mjcf`` on a package that never mentioned MJCF has nothing to
resolve, and ``pc export -t sim-mujoco:mjcf`` has.

The named package goes in as a layer directly above the built-in one rather than
replacing the lot, because this section also decides where the file goes:
``output_dir`` and ``prefix`` are the caller's business whoever writes the file.
So a package that asks for somebody else's exporter still says where the result
lands, and still re-tunes any parameter it wants to.

``readme``, ``pdf`` and ``html`` are the outputs ``render:`` accepts that no
implementation writes: PartCAD assembles them itself out of what the package
declares and the images the other file types leave behind (see ``pc render`` in
:doc:`cli`).

That holds for as long as nobody writes them. A ``pdf:`` or ``html:`` that names
a ``path`` is a package saying that this file is one of its own -- a drawing, a
datasheet -- and PartCAD produces it by running that implementation instead of
assembling the assembly instruction book over it. ``readme`` is the one that
cannot be taken over in practice, not because it is held apart but because
PartCAD ships no implementation of it to replace. See
``examples/feature_render_custom``, where ``pdf``, ``svg`` and ``dxf`` are all
technical drawings produced by an implementation another package publishes.

The package's ``readme`` takes its text from the top-level ``docs:`` section,
and its ``exclude`` also takes ``packages``, which leaves out the list of
sub-packages -- where a package that depends on the public index would
otherwise list the index:

.. code-block:: yaml

  docs:
    name: <(optional) the title; the package's name by default>
    intro: <(optional) a paragraph under the title>
    usage: <(optional) a "Usage" section>
  render:
    readme:
      exclude: [packages]

``docs.name`` is only the title. The top-level ``name`` is the one that says
which package this is.

``urdf`` is the one built-in file type that is not a single file: it writes a
``.urdf`` plus the directory of mesh files it references, which is why
``Shape.convert()`` refuses it (there is no single payload to hand back) and why
it declares ``decode: false`` - it is handed the assembly *tree* itself, one
URDF link per node, rather than the geometry the tree decodes to. Decoding keeps
the shape of the tree but nothing else about it: every node's ``name`` and
``label`` is dropped, and its placement is baked into the geometry instead of
staying readable as the joint origin. See :doc:`simulation`.

.. _cae-section:

Analyses
--------

``cae:`` is a third section of the same shape, and it is where an engineering
analysis is implemented. Its file types are what :ref:`pc cae <cae>` runs, and
every field means what it means above -- ``path`` and ``package`` name the
script, ``pythonRequirements`` and ``pythonVersion`` describe its sandbox,
``extension`` says what the model file is called, and everything else is a
parameter handed to the script:

.. code-block:: yaml

  cae:
    fea:
      path: solve_fea.py
      pythonRequirements:
        - ccx2paraview==3.2.0
      extension: glb          # required: PartCAD has no default to guess at
      mesh_size: 2.0          # a parameter of this implementation

Three things are different from ``export:`` and ``render:``, and all three
follow from an analysis not being a file type of the object:

* **There is no built-in package.** PartCAD ships no solver, so ``cae:`` has no
  bottom layer to fall back on and no fallback section either: an export
  implementation cannot stand in for one, and a ``fea`` declared under
  ``export:`` is an export format that happens to be called ``fea``. Which
  implementation runs by default is the ``caeFeaImplementation`` /
  ``caeCfdImplementation`` user configuration option, naming a package and a
  file type in it.
* **``extension`` is required.** Which model format an analysis writes -- a 3D
  field, a 2D plot -- is the implementation's decision, and guessing on its
  behalf would put a name on a file whose contents are something else.
* **The implementation reports findings.** Beside ``success`` it returns
  ``findings``, a JSON array of what it has to say about the part. An empty one
  is a pass, and is what the ``fea`` and ``cfd`` checks of ``pc test`` require.

The file it writes is named after the analysis as well as the object --
``bracket.fea.glb`` -- because a part has as many results as it has analyses.
What the analysis is *given* is the part's own ``fea:``/``cfd:`` section, which
is a property of the part rather than of whoever analyses it; see
:ref:`pc cae <cae>` for how ``fix:`` and ``load:`` are written and what units
they are in.

.. _cam-section:

Routes
------

``cam:`` is a fourth section of the same shape, and it is where a route -- the
program a machine cuts an object with -- is implemented. Its file types are what
:ref:`pc cam <cam>` produces, and every field means what it means above:

.. code-block:: yaml

  cam:
    gcode:
      path: post_gcode.py
      extension: nc           # required: PartCAD has no default to guess at
      feed: 2400              # a parameter of this implementation ...
      depth_per_pass: 3       # ... and of every object it routes

Two things are different from ``export:`` and ``render:``, and one thing is
different from ``cae:``:

* **There is a built-in package**, unlike ``cae:``. A route is arithmetic on the
  object's own outline rather than somebody else's program with a release cycle
  of its own, which is the test ``export:`` and ``render:`` already pass and a
  solver does not -- so PartCAD ships ``//builtin/cam``, whose ``gcode`` file
  type is what ``camImplementation`` names by default. Nothing has to be
  installed for ``pc cam`` to work.
* **There is no fallback section.** A route is not a file another CAD tool opens
  as a part, so a ``gcode`` declared under ``render:`` is a render format that
  happens to be called ``gcode``, and neither section stands in for the other.
* **``extension`` is required**, for the reason it is required of an analysis:
  what a controller reads is the implementation's decision.

The file it writes is named after the object alone -- ``panel.nc`` -- because an
object has one route at a time and the extension already says what the file is.

**The parameters PartCAD knows by name -- the job: the tool, the depth, the feed
and the rest of the closed list below -- are also keys an object may set for
itself.** Nothing else is: not the parameters that describe the file rather than
the cut, and not a parameter a third-party implementation invented, however
squarely it describes the cut. PartCAD cannot check a name it has never heard of
against a list, which is why the list is closed and why the paragraphs after the
example spell out what is on it. That shared job half is what makes this section
and the object's own declaration layers of one namespace rather than two
different things:

.. code-block:: yaml

  # The package: what this shop does, for every object in it.
  cam:
    gcode:
      feed: 2400 mm/min
      safe_z: 8 mm

  parts:
    stock:
      type: build123d
      path: sheet.py

    panel:
      type: build123d
      path: panel.py
      # The object: what is true of this object, and nothing else. It goes in
      # the section that already says how the part is made, beside the machine
      # it belongs to.
      manufacturing:
        method: subtractive
        source: stock
        cnc:
          operation: profile
          diameter: 6 mm

``//builtin/cam`` is underneath both. So a package cutting twenty parts from one
sheet sets the feed once, and the one part that needs a smaller cutter says so
for itself.

The object's half lives in ``manufacturing:`` and not in a ``cam:`` section of
its own, and that is what makes the word mean one thing. It used to mean two --
the file types a package declares, and the job an object declared -- with the
ambiguity managed by keeping the two key sets disjoint. Now ``cam:`` is the
implementation registry and nothing else, and the job sits where the rest of
"how this is made" already was.

Within the object there are two scopes, and the difference is the point of
having two. What is written directly under ``manufacturing:`` is shared by every
machine the part names; what is written inside a machine's own subsection is
that machine's, and outranks the shared value:

.. code-block:: yaml

  manufacturing:
    method: subtractive
    source: stock
    feed: 1800            # whichever machine cuts it
    laser:
      kerf: 0.15
      power: 85           # the laser's own
    cnc:
      diameter: 3
      depth: 2

**Each machine takes only the keys it reads.** A laser has no ``diameter:`` --
it has no cutter, and ``kerf:`` is what it removes -- and no ``depth:`` or
``safe_z:``, because it cuts through in one pass and never moves in Z. A drill
has no ``depth:`` (how deep each hole goes is the geometry's to say), no
``feed:`` and no ``operation:``. Writing one of those inside that machine's own
subsection is refused with a sentence naming what it does take; writing it in
the shared scope is perfectly legal and simply not read by a machine that has no
use for it.

That distinction is the one a single flat list could not draw. ``tool:`` used to
be one key meaning three things, and a cutter diameter written on a laser-cut
part was a value silently ignored. It is ``diameter:`` now, it lives beside the
machine it belongs to, and on a laser it is an error.

Those are the keys that describe the **cut**. A file type's other parameters
describe the **file** -- ``//builtin/cam``'s ``units``, ``precision``,
``tolerance`` and ``comments`` -- and are set here or by a package rather than by
an object. The line is not tidiness: an object's section is checked against a
list, a list can only hold what PartCAD knows the name of, and PartCAD cannot
know the parameters of an implementation somebody else writes. So a package sets
those for its objects, and the closed set is what buys the error message.

.. _drawing-ports:

Drawing the ports and the interfaces
------------------------------------

A port is a coordinate frame and an interface is a named set of them (see
:ref:`interfaces`), so neither of them is geometry and neither shows up in a
projection. The four projections ``//builtin/render`` implements draw them when
the file type asks:

.. code-block:: yaml

  render:
    svg:
      with_ports: true        # a marker and a name at every port
      with_interfaces: true   # every interface named, and joined to its ports
      with_internals: true    # on an assembly, what is inside it as well
      port_marker_size: 0.1   # the length of a port's +Z arrow ...
      port_label_size: 0.035  # ... and the cap height of the names, as a
                              # fraction of the projection's largest dimension

``pc render --with-ports``, ``--with-interfaces``, ``--with-all`` and
``--with-internals`` ask for the same things for one invocation (see
:doc:`cli`); declaring them on a file type asks for them permanently, which is
how a package keeps a drawing of its connections checked in beside the plain
one. The two add up rather than override: a file type declared with
``with_ports: true`` draws them whether or not the option was given.

On an assembly -- or a :ref:`scene <scenes>`, which is built the same way --
what is drawn is what the assembly says its ports are: the ones its ``map:``
externalizes and the ones it declares (see :ref:`assembly-ports`). Hiding the
rest is the point of externalizing anything. ``with_internals`` walks everything
inside it as well and places each child's ports where the assembly put the
child, so a connection that went wrong is visible as two frames that should have
met and did not.

The two flags reach every ``render:`` file type, this package's own and
another's alike, along with the ports themselves; what an implementation makes
of them is its own business, and one that ignores them draws nothing extra.
Nothing at all is collected for a file type that asks for neither -- and never
for an ``export:`` type, which is a file of geometry rather than a picture.

``examples/feature_interface`` declares four such drawings: two of a part and
two of the assembly it belongs to, each naming ``render_svg.py`` in
``//builtin/render`` as its implementation, in the manner of `Using another
package's implementation`_.
