###########################
Objects and common metadata
###########################

.. _objects:

========
Objects
========

PartCAD :ref:`packages` may contain the following objects:

- :ref:`sketches` are 2D objects that can be used to create 3D objects (e.g. using :ref:`extrude` or :ref:`sweep`),
  but can also be used to aid visualization of :ref:`interfaces` or to provide detailed instructions for AI actors.

- :ref:`interfaces` are abstract objects that describe the endpoint of a connection between parts and provide
  sufficient information to automatically determine the mating of parts.

- :ref:`parts` are 3D objects that are meant to be available for purchase or manufacturing.

- :ref:`assemblies` are instructions how to put parts and other assemblies together to be used as a single object.

- :ref:`scenes` are placed arrangements of objects - a workcell, a table, a simulation world - stating where things
  are and not how they got there.

- :ref:`software` is what the product ships with that is not geometry: a firmware image, a binary, a disk image.
  It is always a file.

- :ref:`providers` are implementations of a way to get parts and assemblies (to purchase them or to manufacture them).

===============
Common Metadata
===============

All :ref:`objects` in PartCAD may carry the following metadata:

.. _tags:

Tags
----

Not everything a package can be built out of exists everywhere. The KiCad
example is the case this was introduced for: KiCad publishes its official
container images for ``linux/amd64`` only, so the sandbox PartCAD runs
``kicad-cli`` in cannot be pulled on an Arm host at all. That is a property of
the design, not a fault in it, and the package saying so is better than every
consumer of it finding out at use.

A **tag** is a short string naming something that is true of *here*. Every
context carries the tags true of itself.

What the machine is:

* the CPU architecture -- ``x86_64`` and ``amd64`` on 64-bit Intel/AMD,
  ``arm64``, ``aarch64`` and ``arm`` on 64-bit Arm (all of them, so that a
  package need not know which spelling the host happens to report);
* the operating system -- ``linux``, ``macos`` (also ``darwin``), ``windows``;
* the operating system and its version, as ``<os>-<version>``. On Linux that is
  the distribution rather than the kernel, read from ``/etc/os-release``:
  ``ubuntu`` and ``ubuntu-24.04``, plus whatever ``ID_LIKE`` names (``debian``).
  On macOS, ``macos-26`` and ``macos-26.1``. On Windows, ``windows-11``.

How PartCAD is configured to work -- one tag per boolean option, carried in one
of two spellings, the option's name when it is on and that name prefixed with
``!`` when it is off:

* ``useDocker`` / ``!useDocker`` -- whether PartCAD may use Docker at all;
* ``useDockerPython`` / ``!useDockerPython``;
* ``useDockerKicad`` / ``!useDockerKicad``.

These report each option **as configured**, not as it ends up applying:
``useDocker`` is a master switch over the other two, so ``useDockerKicad`` and
``!useDocker`` can hold at once. Both spellings exist so that either answer can
be named -- a package that cares which way an option is set should not have to
guess what an absent tag meant. Note that ``!`` is part of a tag's name, not an
operator: a tag is matched, never evaluated, and ``!`` means nothing anywhere
else.

Anything PartCAD cannot work out for itself -- that this is the build machine,
that this host is behind a proxy -- is added by the user, through the ``tags``
user configuration option (``pc config`` shows it) or the ``PC_TAGS``
environment variable. ``pc system status`` prints the whole resolved set:

.. code-block:: console

  $ PC_TAGS="build-machine" pc system status
  INFO: Tags: aarch64, arm, arm64, build-machine, debian, linux, ubuntu, ubuntu-24.04, useDocker, useDockerKicad, !useDockerPython

Tags are matched case-insensitively, and are shown in the spelling PartCAD names
them by -- which is why ``useDocker`` is camelCase (it is an option name) and
``arm64`` is not.

A package, or any object of a package, may then declare the conditions it does
**not** work under, using ``unless``:

.. code-block:: yaml

  # The whole package is skipped on an Arm host that will run KiCad in a
  # container -- but not on one where KiCad has been configured to run natively
  unless: [[arm, useDocker, useDockerKicad]]

  parts:
    pcb:
      type: kicad
      # ... or just this one part, and on any Arm host
      unless: arm

``unless`` is a list of **clauses**, and *any one* of them excluding is enough
(OR). A clause is either a single tag, or a list of tags that must *all* hold
together (AND). Either level may be written as a bare tag when there is only
one, so all of these are valid:

.. code-block:: yaml

  unless: arm64                                   # one tag
  unless: [arm64, windows]                        # either one excludes
  unless: [[arm, useDocker], macos]               # both of the first, or macOS

An empty clause is refused rather than ignored: it would hold everywhere.

Wherever a clause holds, the declaration is skipped -- it is not enumerated, not
listed, and not instantiated -- and PartCAD says so once, at ``INFO``, naming
the clause that did it:

.. code-block::

  INFO: Skipping the package '//pub/examples/partcad/produce_part_kicad': excluded by 'unless' (arm and useDocker and useDockerKicad)

Skipping a package skips what it brings in: its subfolders and its declared
dependencies are not imported either.

Note that there is deliberately no inverse condition ("only on"). A declaration
is expected to work everywhere; naming the exceptions keeps the common case
unwritten, and keeps a platform that does not exist yet from silently excluding
everything written before it.

A reference to an object that was skipped does not resolve. An alias or an
``enrich`` built on an object excluded here has to carry the same ``unless``, or
it will be left pointing at nothing.

.. _requirements:

Requirements
------------

A part, an assembly, a scene or a sketch may say what it is required to be.
Requirements are written before the design is, from the point of view of
whoever asked for it, and they are what the design is judged against: by
``pc test``, by the simulations that name them, and by whoever reads the
evidence -- a person, or an AI agent running ``/pc:validate``. The PartCAD
extension for Visual Studio Code shows them on a tab of their own, in front of
the others, with a mark beside each that ``pc test`` checks.

They are from the user's perspective and serve to guide the design. Once the
design is complete it may impose further requirements of its own -- on
manufacturing, say -- but those are not part of this section.

.. code-block:: yaml

  parts:
    bracket:
      type: build123d
      requirements:
        features:
          mounting: Four M3 clearance holes on a 40 mm square, reachable from the top
          shelf-load: Holds a 2 kg shelf at its free end without visible bending
        ports:
          top: [null, [0, 0, 1], null]
        interfaces:
          //pub/std/metric/m3:m3-thru: null
        physics:
          mass: "<0.05"

``features``
  What the object has to have or do: a name for each, and a sentence saying
  what. Most of what anybody asks of a product is said this way, and PartCAD
  does not judge it. A ``simulate:`` entry may name the feature it demonstrates
  (``feature:``, see :doc:`simulation`); every feature, demonstrated or not, is
  for whoever reads the evidence to judge -- the renders, the simulations, the
  bill of materials and the assembly instructions. That is what the
  ``/pc:validate`` agent skill does.

``ports``
  The ports the object has to have, by name, and as much of where each one is
  as matters. ``null`` only requires that the port is there.

``interfaces``
  The interfaces the object has to implement, named the way ``implements:``
  names them. Implementing an interface that inherits a required one counts:
  something that implements ``m3-thru`` implements ``m3``. ``null`` requires
  any instance, anywhere; a location requires that some instance is there; an
  instance name, a list of them, or a mapping of instance names to locations
  requires those instances (``""`` is the unnamed one).

``physics``
  The physical properties the object has to have: any field of a ``physics``
  section a shape may state (see :doc:`simulation`) -- ``mass``,
  ``centerOfMass``, ``inertia``, ``density``, ``friction`` and the rest. The
  value checked is the one ``pc info`` reports: what the object states in
  ``properties: physics:``; failing that, what its material lends (its
  ``density``, and its ``mu`` as the ``friction``); failing that, what its solid
  works out to -- the mass at that density, the centre of mass, the inertia --
  or for an assembly what its parts add up to. A property PartCAD cannot find
  out fails the requirement: not known is not met, and that includes the mass of
  an assembly one of whose parts weighs nothing PartCAD knows, since what the
  others add up to is not what it weighs.

``pc test`` checks the last three against the model -- its ``requirements``
check, ``pc test -f requirements`` to run it alone -- and says, for each one
that is not met, what it found instead.

Required values
^^^^^^^^^^^^^^^

Almost anything in a port, an interface or a physical property can be
``null``, and most of it should be: ``null`` is no requirement. "A port called
``top`` that faces down" is a requirement; "a port at these exact coordinates"
is usually a design decision written down too early.

What is not ``null`` is a constant -- a number, a string or a boolean -- or a
comparison: ``>0``, ``>=1``, ``<10``, ``<=1``, ``!0`` (not 0, also ``!=0``) or
``=5``. Several are joined with commas, and the two kinds join differently:
constants are alternatives, comparisons all have to hold, and a value given both
has to be one of the constants *and* meet every comparison.

.. code-block:: yaml

  mass: 0.5          # 0.5, to within 1e-6
  mass: "<0.5"       # less than 0.5
  mass: ">0,<=0.5"   # in (0, 0.5]
  maxContacts: "1,2,4"   # one of the three
  maxContacts: "1,2,3,!2" # 1 or 3

Quote a comparison: YAML reads ``>`` and ``!`` at the start of a value as
syntax of its own.

Where a port or an interface instance is
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

A location requirement is three things, each of which may be ``null``:

``position``
  Where the frame's origin is, in millimetres, in the object's own frame.
``direction``
  The way the frame's Z axis points -- the way a port *faces*. Three plain
  numbers are compared as the unit vector they point along.
``angle``
  How far, in degrees, the frame is turned about that direction: how far its X
  axis is from where the shortest turn from +Z to the direction leaves it. For a
  port written as a turn about Z, that is the angle it was written with.

They are written as a mapping by those names, or as a list of three in that
order -- the order a port's own location is written in:

.. code-block:: yaml

  ports:
    top: [null, [0, 0, -1], null]       # faces down, anywhere
    side:
      position: [">0", null, null]      # somewhere on the +X side
      direction: [1, 0, 0]              # facing +X
      sketch: m3                        # and drawn with the sketch 'm3'
  interfaces:
    m3-thru: [TL, TR]                   # these two instances, anywhere
    rail:
      "": [[0, 0, null], null, 90]      # the unnamed one on the Z axis, turned a quarter turn

The middle element of a *port's* location is the axis it is rotated about, and
of a requirement it is the direction the port faces. They are not the same
thing, deliberately: a port facing down is written ``[[0, 0, 0], [1, 0, 0],
180]`` -- half a turn about X -- and it meets the requirement ``[null, [0, 0, -1],
null]``.

Earlier spellings
^^^^^^^^^^^^^^^^^

The section used to be free-form text, and that is still read -- as features: a
paragraph is the feature ``general``, a list is one feature per item, and a key
of the mapping that is not one of the four above is a feature named after it.

.. code-block:: yaml

  parts:
    <part name>:
      requirements:
        mechanical: |
          The outer dimensions of the part have to be ...
        esthetic: |
          The part has to look like ...

.. _files:

Files
-----

For objects that are defined using a source file, the default file path is
the name of the object plus the extension of that file type.

An alternative file path (absolute or relative to the package path)
can be defined explicitly using the `path` parameter:

.. code-block:: yaml

  parts:
    part-name:
      type: step
      path: alternative-path.step # Instead of "part-name.step"

When the source file is not kept in the package source repository but has to be
pulled from a remote location (a STEP file published by the part vendor, for
example), declare where to get it from using ``fileFrom`` and ``fileUrl``:

.. code-block:: yaml

  parts:
    bolt:
      type: step
      path: bolt.step # (optional) where to place the file once it is downloaded
      fileFrom: url # "url" is the only source supported so far
      fileUrl: https://example.com/vendor/catalog/bolt.step

The file is fetched lazily: nothing is downloaded until the object is used for
the first time, and the downloaded file is reused afterwards. Since the file is
not expected to be a part of the package, PartCAD does not complain about it
being missing while the package is loaded.

``fileFrom`` and ``fileUrl`` must be declared together.
They are recognized in :ref:`parts`, :ref:`sketches`, :ref:`assemblies`
(an assembly's source file is pulled the same way, whether it is an ``.assy``
file or a CAD file), :ref:`scenes` and :ref:`software`.

.. _file-hash:

Pinning what is downloaded
^^^^^^^^^^^^^^^^^^^^^^^^^^

A URL serves whatever it serves at the moment it is fetched. The same
declaration can produce a different file tomorrow -- the vendor revises the
model, the branch moves, the host is not the one you thought. ``fileHash``,
beside ``fileUrl``, pins the bytes:

.. code-block:: yaml

  parts:
    bolt:
      type: step
      fileFrom: url
      fileUrl: https://example.com/vendor/catalog/bolt.step
      fileHash: sha256:2c26b46b68ffc68ff99b453c1d30413413422d706483bfa0f98a5e886266e7ae

The download is refused unless the file hashes to this, and the bytes that were
refused are deleted rather than left behind -- the next run skips the download
when the file is already there, and would otherwise reuse the file the hash had
just rejected.

Write it as ``<algorithm>:<digest>`` over ``md5``, ``sha1``, ``sha256`` or
``sha512``. A bare digest works too, and the algorithm is read from its length,
which is the form most vendors publish.

``fileHash`` is recognized wherever ``fileFrom`` is, and it is **optional but
required for reproducibility**. The schema never demands one, of any kind of
object, and nothing refuses to load, build or lint an object that omits it.
What such an object cannot do is promise that the next run produces the same
thing, and manufacturing is repetition -- so ``pc test`` refuses to call it
manufacturable (see :ref:`reproducibility`). Pull a vendor's model down and
never claim it can be made, and none of this touches you.

``pc add`` writes one for you. Given a URL instead of a path it fetches the file
once and records the hash of what came back, so an object added that way is
pinned from the moment it exists.

A file served by a repository plugin -- what PartCAD uses for a package with no
source tree of its own -- may carry a ``fileHash`` too, and it is verified the
same way. It is not yet required, because nothing has been put in place for such
a package to pin what its plugin serves.

This has nothing to do with the hashes PartCAD computes for itself -- a shape's
cache key, or the commit a package was read at. Those identify something PartCAD
built or fetched; ``fileHash`` states, in advance, which bytes a package is
asking for.

.. _reproducibility:

Reproducibility and manufacturability
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^

Manufacturing is repetition: the run after this one has to produce the same
thing, so everything that goes into a product has to be gettable a second time
and be the same thing. There are three ways an object can promise that, and the
``manufacturability`` check of ``pc test`` fails one that offers none of them:

- **It is bought.** A ``vendor`` and an ``sku`` name a thing to order, and
  ordering it again is what "the same again" means for it -- whatever file the
  declaration also carries is a drawing of what arrives rather than the identity
  of it. Only :ref:`parts` and :ref:`assemblies` can say this; the schema gives
  ``vendor``/``sku`` to those two alone.
- **The package carries the file.** Its revision identifies the file exactly.
- **The file is pinned** with a ``fileHash``.

A :ref:`sketch <sketches>` cannot be bought, so for it the second and third are
the whole of it -- nothing manufactures a drawing, but a part extruded from one
is no more repeatable than the drawing was. :ref:`software` is the same case,
and for the same reason: a firmware image nobody can identify makes the bill of
materials that names it worthless.

.. code-block:: text

  Test failed: //robot:bracket: manufacturability: It is not reproducible: it is
  fetched with 'fileFrom: url', declares no 'fileHash', and names no vendor and
  SKU to order it by, so nothing says which one it is

The rule is about being *identified*, not about being available -- the file may
download perfectly well and still be a different file than it was last month.

Software is the one kind of object where a missing ``fileHash`` is reported by
``pc lint`` as well, before anything is built or fetched at all.

A file served by a repository plugin is exempt from all of this for now. A
``fileHash`` given for one is verified like any other; it is simply not required
yet, because nothing has been put in place for a plugin-backed package to pin
what its plugin serves.

Parameters
----------

Objects may declare parameters. Once parameters are declared, each use of such objects may be accompanied
by a set of parameter values. The parameter values are resolved and applied to the object to create a parametrized
variant of the object. The parametrized variant remains stored (e.g. at runtime) as a separate object in the same
package where the original object is declared. This allows for the same parametrized object to be used multiple times.

.. code-block:: yaml

  parts:
    <part name>:
      parameters:
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

The short form ``<param name>: <default value>`` may be used whenever the type
can be inferred from the value.

Assemblies declare parameters the same way. Their values are passed to the
``.assy`` file as ``param_<param name>`` when its Jinja templates are resolved:

.. code-block:: yaml

  assemblies:
    <assembly name>:
      type: assy
      parameters:
        offset: 5.0

.. code-block:: yaml

  links:
    - part: //package:part
      location: [[0, 0, {{ param_offset }}], [0, 0, 1], 0]

One parameter of an ``assy`` assembly is PartCAD's own rather than the file's:
``exploded``, ``false`` unless something sets it. Set, the assembly is drawn
with its items pulled apart -- each one backed out of what it is connected to,
along the connection, by the ``exploded:`` of its ``connect:`` or
``connectPorts:`` section (see :doc:`assy`) or by half of the larger of the two,
and carried along with whatever it is connected to that has moved itself. It is
the same gap an assembly instruction book shows each step with.

Only the assembly's own items move. An item that is an assembly itself -- a
sub-assembly, or a nested ``links:`` list -- moves as one piece, with everything
in it where it was. Whatever belongs to an item moves with it: its ports are
drawn on it where it is drawn (``--with-ports``, ``--with-internals``), and so
is a port the assembly's ``map:`` takes from it.

``logo;exploded=true`` is a parametrized variant like any other: an object of
its own, with a cache key of its own, so it is built, rendered and exported once
and read back from the cache afterwards. ``pc render logo -p exploded=true``
asks for it from the command line (see :ref:`parameter-values`), and an alias
gives it a name of its own:

.. code-block:: yaml

  assemblies:
    logo:
      type: assy
    logo_exploded:
      type: alias
      source: :logo
      with:
        exploded: true

Only the ``assy`` type accepts it, because only an ASSY file says what each item
is connected to; declaring ``exploded`` on an assembly read from a STEP file is
an error.

Other
-----

There are other optional fields that are common to all objects:

- ``desc``: <text>

  Description of the object.

- ``offset``: <OCCT Location object>

  Defines the offset to apply to the CAD model when this object is used.

- ``cache``: <bool> (default: `True`)

  The value `false` indicates the intent to exclude this object from any caching behavior.
  It may be due to storage size or time considerations, or due to known issues with dependency tracking.
  It does not override any global caching settings.
