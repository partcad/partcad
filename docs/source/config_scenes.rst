######
Scenes
######

.. _scenes:

What a scene is
===============


A scene is a placed arrangement of objects - a workcell, a table with parts laid
out on it, a simulation world. It is built out of the same files as an assembly,
and differs in intent: an assembly is a product that was put together, and a
scene states only where things are. A scene can also say what its world is
like, the gravity in it and the fluid it is filled with, and it is what a
simulation places an object in. A Gazebo world or a MuJoCo model is read as a
scene, and a scene is written out as either, through the engine's plugin
package. See :ref:`scenes` and :doc:`/digital_thread/workflows/simulation`.


A **scene** is a placed arrangement of objects: a workcell, a table with the
parts laid out on it, a simulation world. It is built the way an assembly is,
out of the very same files, and everything that works on an assembly works on a
scene -- it renders, it exports, it has a bill of materials, ``pc ide view``
shows it.

What separates the two is intent, and one rule follows from it. An assembly is a
*product*: it says what it is made of and, through the ``how:`` section of each
``connect:``, how it is put together, which is what the
assembly instruction book (``pc render -t pdf``) is generated from. A scene
states only an end state. Nothing in it was assembled, so there is nothing to
say about the assembling, and ``how:`` is rejected rather than ignored (see
:doc:`/assy`).

Declare scenes
==============

.. code-block:: yaml

  scenes:
    <scene name>:
      type: <assy>  # Assembly YAML read as a scene. An engine's own scene format is
                    # implemented by that engine's plugin package and named through it:
                    # "sim-gazebo:world" (a Gazebo world), "sim-mujoco:mjcf" (a MuJoCo model).
      desc: <(optional) textual description>
      path: <(optional) the source file path>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      fileHash: <the bytes to expect; required with "fileFrom", see "Files">
      parameters:  # (optional) same as for assemblies
        <param name>:
          type: <string|float|int|bool>
          default: <default value>
      dependencies: # (optional) the list of filenames the caching logic checks for changes
        - <macros.j2>
      offset: <(optional) OCCT Location object>
      manufacturable: <(optional) false by default; a scene is not a product to be made>
      gravity: <(optional) [x, y, z] in m/s^2; the engine's own, Earth's along -Z, by default>
      medium: <(optional) the material the scene is filled with; a vacuum by default>
      simulate: <(optional) what the scene is supposed to do once the world is switched on; see "Simulate a scene" below>

      # 'sim-gazebo:world' only -- the reader's own parameters, declared by the
      # package that implements it and passed straight through to it
      ignoreCollision: <(optional) build a link from its visual geometry instead>
      modelPaths: <(optional) roots to resolve 'model://' references against>

The declaration points at the file that holds the scene and nothing else: there
is no assembly object in between. An ``.assy`` file in an ``assemblies:``
section is an assembly, and the very same file in a ``scenes:`` section is a
scene.

.. code-block:: yaml

  scenes:
    workcell:
      type: assy
      desc: The robot, the fixture and the bin, where they stand on the bench

    warehouse:
      type: sim-gazebo:world
      desc: A Gazebo world, used where it lies

Scenes take parameters, aliases and enriches exactly as assemblies do:

.. code-block:: yaml

  scenes:
    workcell_wide:
      type: enrich
      source: :workcell
      with:
        spacing: 900

A scene's ASSY file may place another scene (``scene:``) and weld what a link
places to the world (``fixed: true``), and neither is allowed in an assembly: in
a scene every element is a rigid body of its own, and in an assembly everything
is attached to it. See :ref:`assy-scenes` for the keys and :ref:`sim-bodies` for
the rule.

Simulate a scene
================

A scene can be the thing a claim is about, not only the world it is tested in:
a stack of blocks that stands, a pile that does not slide. It declares
``simulate:`` exactly as a part or an assembly does (see :ref:`sim-declaring`),
and is simulated as the subject of a world -- the built-in one, or a scene of the
package's own -- whose link places it with ``scene:``, since PartCAD hands that
world ``subject_kind: scene``:

.. code-block:: yaml

  scenes:
    stable:
      type: assy                      # two blocks, one set on the other
      simulate:
        stands:
          simulation: sim-mujoco:mujoco
          offset: [[0, 0, 10], [0, 0, 1], 0]
          validation: |
            max(abs(after["bodies"][n]["pos"][2] - before["bodies"][n]["pos"][2]) for n in before["bodies"]) < 5.0

``pc sim stable`` runs it, and ``pc test`` holds the scene to it as its
``sim`` check like any other object. ``examples/feature_simulate`` declares its
three stacks this way.

Gravity, and the fluid a scene is filled with
=============================================

A scene is a world as well as an arrangement, and may say two things about that
world which an assembly cannot: the gravity in it, and the fluid it is filled
with.

.. code-block:: yaml

  scenes:
    tank:
      type: assy
      gravity: [0, 0, -9.81]
      medium: //pub/std/manufacturing/material/fluid:water

``gravity:`` is a vector in **m/s^2**, in the scene's own frame: ``[0, 0, -9.81]``
is Earth with Z up, ``[0, 0, -1.62]`` the Moon, ``[0, 0, 0]`` free fall. It is
SI because every physical quantity PartCAD states is SI -- only lengths and
angles are millimetres and degrees (see the note under :ref:`materials`) -- and
it is also the number every reader knows, every engine states, and the unit a
``simulate:`` passes its plugin a gravity in; see :ref:`sim-scenes`. A scene
that states none leaves it to the engine, whose own default is Earth's along -Z.
Anything but three numbers is an error, and a gravity above 1000 m/s^2 -- a
vector written in mm/s^2 by mistake is a thousand g -- is reported as one that
is probably in the wrong unit.

``medium:`` names a :ref:`material <materials>`, resolved the way a part's
material is (``:brine`` is the ``brine`` this package catalogues), and its
``density`` (kg/m^3) and ``viscosity`` (Pa*s) are what a simulation drags and
buoys what moves through the scene with.
``//pub/std/manufacturing/material/fluid`` catalogues ``air``, ``water`` and
``seawater``. A scene that names none is a vacuum, which
is what every engine assumes.

Both defaults are what a scene meant before it could say either, so a scene
that says neither simulates and exports exactly as it always did. A medium that
names a material nothing answers to is an error rather than a vacuum, a medium
whose material states neither a density nor a viscosity is reported, and
``pc info`` reports the world a scene resolved to -- the gravity and the facts of
the material it is filled with. What each engine makes of it, and what it does
not model, is in :ref:`sim-engines`.

Gazebo worlds
=============

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

MuJoCo models
=============

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
