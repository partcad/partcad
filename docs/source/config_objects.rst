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

Objects may contain a list of requirements in free form (any YAML syntax works).
These requirements help describe the object in more detail.
They are not used by PartCAD itself, but by AI or human actors to create,
improve, or better understand the object.

The requirements are from the user’s perspective and serve to guide the design.
Once the design is complete, it may impose further requirements (for example,
on manufacturing), but those are not part of this section.
This section exclusively covers the requirements used to create the design.

.. code-block:: yaml

  parts:
    <part name>:
      requirements: |
        This part has to ...
        ...
        It also has to ...
        ...

.. code-block:: yaml

  parts:
    <part name>:
      requirements:
        - <requirement 1>
        - <requirement 2>
        - <requirement 3>

.. code-block:: yaml

  parts:
    <part name>:
      requirements:
        mechanical: |
          The outer dimensions of the part have to be ...
        electrical: |
          The part has to be able to withstand ...
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
