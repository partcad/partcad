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
package. See :ref:`scenes` and :doc:`/digital_thread/lifecycle/simulation`.


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
angles are millimetres and degrees (see the note under :ref:`materials`). A scene
that states none leaves it to the engine, whose own default is Earth's along -Z.
Anything but three numbers is an error, and a gravity above 1000 m/s^2 -- a
vector written in mm/s^2 by mistake is a thousand g -- is reported as one that
is probably in the wrong unit.

``medium:`` names a :ref:`material <materials>`, resolved the way a part's
material is (``:brine`` is the ``brine`` this package catalogues), and its
``density`` (kg/m^3) and ``viscosity`` (Pa*s) are what a simulation drags and
buoys what moves through the scene with.
``//pub/std/manufacturing/material/fluid`` catalogues ``air``, ``water`` and
``seawater``. A scene that names none is a vacuum, which is what every engine
assumes. A medium naming a material nothing answers to is an error rather than a
vacuum, and one whose material states neither a density nor a viscosity is
reported.

``pc info`` reports the world a scene resolved to. What each engine makes of
either key, and what it does not model, is in :ref:`sim-scenes` and
:ref:`sim-engines`.

Scene types a plugin adds
=========================
Beside ``assy``, a scene may be declared in a format an :doc:`import plugin
</plugins/importers>` reads, and PartCAD itself ships none of them:

``sim-gazebo:world``
  An `SDFormat <http://sdformat.org/>`_ ``.world`` file, read as a scene
  directly. Declared by
  `partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_.

``sim-mujoco:mjcf``
  A `MuJoCo <https://mujoco.org/>`_ model, which is the one format that is both
  a scene type and an assembly type -- the section that declares it is what
  decides which. Declared by
  `partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_.

Both are read, written and opened by the same package that simulates the format.
:doc:`/plugins/importers` describes each in full, with the commands that import,
export and convert between them.

Simulating a scene
==================
A scene can be the thing a claim is about, not only the world another object is
tested in: a stack of blocks that stands, a pile that does not slide. It
declares ``simulate:`` exactly as a part or an assembly does, and ``pc sim`` and
``pc test`` hold it to it. See
:ref:`Simulating a scene <validating-a-scene>` in the Validation phase.
