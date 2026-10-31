.. _import-section:

#########
Importers
#########

An **import plugin** teaches PartCAD to read a file format. ``urdf``,
``sim-mujoco:mjcf`` and ``sim-gazebo:world`` are not object types PartCAD
hard-codes: each is one entry of an ``import:`` section -- a declaration saying
which script reads that format, what its sandbox needs, and which object kinds
it may produce -- and a package writes one to teach PartCAD a format of its own.

That is not a hypothetical. ``urdf`` is the only one of those three PartCAD
ships, and the other two are entries of exactly this kind in the plugin package
for their engine.

What an importer is for
=======================

- **Reading somebody else's description of an assembly or a scene** -- a robot
  in URDF, a world in SDFormat, a model in MJCF -- so that it becomes objects
  of a package and can be inspected, rendered, exported and simulated like
  anything else PartCAD declares.
- **Bringing a vendor format into the thread** without converting it first. The
  file stays the source of truth, and PartCAD reads it again whenever it changes.
- **Giving a format a round trip.** Reading and writing one format are one piece
  of knowledge, so a package that declares the importer usually declares the
  matching :doc:`export type </plugins/output>` beside it, and
  ``pc convert`` then moves objects between the two.
- **Teaching a proprietary or in-house format** to PartCAD in one place, as a
  package your other packages import, rather than converting files by hand.

Using one
=========

Import the package that declares the format and name the type through it. The
section the declaration goes in -- ``assemblies:`` or ``scenes:`` -- is what says
what the file *is*:

.. code-block:: yaml

  dependencies:
    sim-gazebo:
      type: git
      url: https://github.com/partcad/partcad-sim-gazebo

  scenes:
    cell:
      type: sim-gazebo:world       # the reader in the imported package
      path: cell.world

Three commands exist for a file the package does not declare yet:

.. code-block:: shell

  pc import scene -t sim-gazebo:world warehouse.world   # read it in, as PartCAD's own objects
  pc add scene sim-gazebo:world warehouse.world         # declare the file where it lies
  pc convert scene -t assy :warehouse                   # turn a declared one into PartCAD's own format

``pc info`` on the result reports what the reader had to drop, which is the first
thing to look at after importing anything.

Writing one
===========

One entry per format, in an ``import:`` section:

.. code-block:: yaml

  import:
    demo:
      desc: The DemoCAD scene format
      path: read_demo.py           # the reader, in this package
      extension: demo              # the source file's extension
      kinds: [assembly, scene]     # what it may be declared as
      noun: model                  # what one is called in a log line
      pythonRequirements:
        - cadquery-ocp-novtk==7.9.3.1.1
      precision: 6                 # anything else is the reader's parameter
      dropped:
        joint: "joints (the object shows the bodies at their initial pose)"

An object then names it the way it names any object type. A reader in the same
package is named directly; one in another package is named by full path, exactly
as a :ref:`partType <part-types>` or a ``simulation:`` plugin is.

The reader itself is handed the file and its parameters, and returns a tree of
placed shapes as plain data -- each node naming the *file* its geometry is read
from rather than carrying geometry. The part factory for that file's own format
reads it afterwards, so a mesh a scene references is never copied or rewritten.
Only the primitives a format defines (a box, a cylinder, a sphere) have no file
to name, and the reader writes those out itself. See
``wrappers/wrapper_import.py`` for the contract in full.

The file is a Jinja2 template like every other text file an assembly or a
scene is declared by, and is rendered before the reader sees it. A format whose
files are bytes (a DWG, say) says so, and its files are handed to the reader
exactly as they are on disk, never opened as text:

.. code-block:: yaml

  import:
    dwg:
      path: read_assembly.py
      extension: dwg
      binary: true

It is the declaration that decides, never the file's content: a binary file
whose bytes happen to decode is still not rendered, and a text format's file
that is not UTF-8 is reported as the broken template it is. Every object
PartCAD reads from a file is one of three kinds in this respect -- handed over
as it is, rendered as a template, or bytes -- and ``partcad.file_source`` is
where that is decided.

A reader runs where an output implementation of the same package would: in the
sandbox its own package describes (``pythonVersion``, ``pythonRequirements``,
``dockerImage``), never the one the package declaring the object does. It is
also handed ``request["cache_dir"]``, the directory its package keeps what it
downloads on first use in -- a converter pip cannot install, for one -- exactly
as a ``partType`` and an output implementation are.

Two fields are worth dwelling on. ``kinds:`` is a claim the core holds the
declaration to: a format that describes one robot is an assembly and declaring
it under ``scenes:`` is an error, while a format used for both -- MJCF is the
one that routinely is -- says both and lets the section decide. ``dropped:``
words what the reader counted: every one of these formats describes something a
static tree cannot hold, and the division of labour is that the *reader* counts
what it had to drop and the *declaration* says what to call it.

The section shares its name with what ``dependencies:`` used to be called, and
that spelling is reported rather than silently migrated now: a package whose
``import:`` entries carry a ``type:`` of ``git``/``tar``/``local``/``external``,
or any of the transport-only keys (``url``, ``relPath``, ``revision``, ...), is
told to rename the section, and those entries are dropped instead of being
fetched as packages. Nothing is migrated for it.

How loudly depends on whose package it is. In the package you are standing in it
is an error and the package is broken -- the command exits non-zero and nothing
loads out of it, because that is the file you can fix. In an imported package it
is a warning naming the package, the entry and the fix: such a package is very
often somebody else's, several levels below anything you wrote, and one of them
anywhere in an index must not fail every command that merely walks past it. That
package goes on providing everything else it declares; what is lost is exactly
what the section named.

PartCAD ships **one** of these, in ``//builtin/import``: ``urdf``, which stays
there because a URDF describes a robot rather than any one engine's world, and
ROS, MuJoCo, PyBullet and Isaac all read it. ``mjcf`` and ``world`` belong to
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ and
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_
respectively, beside the exporter and the simulator that share their knowledge
of the format: reading a format and writing it are one piece of knowledge, and
this is what lets the pair travel together and be versioned together.

Each of those packages declares the reader, the writer, the simulator and the
``open:`` entry for its format, and the wheel carries none of them. So
``type: sim-gazebo:world`` and ``type: sim-mujoco:mjcf`` are the spellings that
resolve, in a package that imports the plugin; a bare ``type: world`` resolves to
nothing and says which package to name.

Examples
========

Both of the formats below are read, written, opened and simulated by one
package each, which is the shape to copy: the knowledge of a format belongs
beside the engine that uses it.

Gazebo worlds -- ``sim-gazebo:world``
-------------------------------------

The ``sim-gazebo:world`` type reads an `SDFormat <http://sdformat.org/>`_
``.world`` file -- what Gazebo describes a simulation world in -- as a scene
directly, with no conversion step. It is declared by
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_ rather than
by PartCAD itself, beside the exporter, the ``pc ide open`` entry and the simulator
that share their knowledge of the format, so a package that uses it imports that
package and names the type through it. Every model is placed where its ``<pose>`` puts it, every link
where its own pose puts it inside the model, and every shape becomes a part of
the package named ``<scene>/<model>/<link>``. Those parts are ordinary parts:
they can be inspected, rendered and exported on their own.

.. note::

   "SDF" means two unrelated things in PartCAD. The ``sdf`` *part* type is a
   signed distance function. This is **SDFormat**, and PartCAD calls it
   ``world`` throughout, after the files it lives in.

It is a best-effort reader: SDFormat describes a running simulation and a scene
describes where things are, so joints, lights, sensors, plugins, actors, physics
settings and the ground plane are counted and reported rather than passed over
in silence. ``pc info`` lists what was dropped. See :ref:`sim-engine-formats`
for the whole picture.

The reverse direction is the ``sim-gazebo:world`` export file type, declared by
the same package:

.. code-block:: shell

  pc export -t sim-gazebo:world :workcell       # writes workcell.world plus its meshes

and ``pc convert scene`` moves a scene between the two formats, rewriting the
package around it:

.. code-block:: shell

  pc convert scene -t assy :warehouse                # the world's shapes become parts of the package
  pc convert scene -t sim-gazebo:world :workcell     # the scene becomes a Gazebo world file

``pc import scene -t sim-gazebo:world warehouse.world`` does the first of those
in one step for a file the package does not declare yet, leaving the package
holding PartCAD's own objects. ``pc add scene sim-gazebo:world warehouse.world``
declares the file where it lies instead.

MuJoCo models -- ``sim-mujoco:mjcf``
------------------------------------

The ``sim-mujoco:mjcf`` type reads a `MuJoCo <https://mujoco.org/>`_ model as a
scene, the same way ``sim-gazebo:world`` reads a Gazebo one. It is declared by
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_, for the
reason the world type is declared by the Gazebo one: every body is placed where its ``pos``
and orientation put it inside the body that holds it, and every geom becomes a
part of the package named ``<scene>/<body>``.

It is the one format that is **both** a scene type and an assembly type, and
which of the two a given file is depends on the section that declares it rather
than on the file. A URDF describes one robot and a ``.world`` describes one
world; an MJCF file is used for both -- the same element holds a manipulator and
the table it is bolted to -- and nothing in it says which it is. So the package
says so:

.. code-block:: yaml

  assemblies:
    arm:
      type: sim-mujoco:mjcf
      path: arm.xml        # a product

  scenes:
    cell:
      type: sim-mujoco:mjcf
      path: cell.xml       # an arrangement

It is a best-effort reader in the same way the world reader is: joints,
actuators, tendons, sensors, lights, cameras, contacts and keyframes are counted
and reported, and ``pc info`` lists what was dropped. The reverse direction is
the ``sim-mujoco:mjcf`` export file type, which writes an ``.xml`` file plus the
meshes it references:

.. code-block:: shell

  pc export -t sim-mujoco:mjcf :cell        # a scene
  pc export -t sim-mujoco:mjcf :arm         # or an assembly

It is also the format ``pc sim`` hands a scene to MuJoCo in (see
:ref:`sim-engines`), and the one ``pc ide open --with mujoco`` expects a file to
already be in (see :ref:`sim-opening`).
