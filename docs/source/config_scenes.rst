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
      type: <assy|walls>  # Assembly YAML read as a scene, or the walls of a room standing on a
                    # sketch (see "Rooms" below). An engine's own scene format is
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

.. _scenes-walls:

Rooms: the walls standing on a sketch
=====================================
For laying out a space rather than making anything -- a floor plan, an apartment
for sale, the room a machine is going to stand in -- a scene can be the walls of
a room, worked out from a sketch of its plan:

.. code-block:: yaml

  sketches:
    living-room-plan:
      type: dxf          # or any sketch: one closed outline, drawn from above

  scenes:
    living-room:
      type: walls
      sketch: living-room-plan
      height: 2700                    # mm
      wall: //builtin/building:wall   # (optional) the part each wall is

The sketch has to be **one enclosed outline** made of **straight lines and arcs of
circles**, on the XY plane: a face with no holes in it, a closed wire, or loose
edges that join into one. The scene is one :ref:`wall <walls>` per edge of it,
named ``wall-1``, ``wall-2``, ... in the order a walk around the outline meets
them, each standing where its edge starts and turned the way the edge goes. A
line is a straight wall and an arc an arc wall of the arc's radius and length.

Every wall looks into the room, whichever way round the outline was drawn: the
walk goes clockwise, and a wall is seen from its right. So a picture of the
room taken from outside is taken *through* the walls nearest the camera, and
shows the far walls from the inside, the way a dollhouse or a sales brochure
shows a flat. From straight above, every wall is seen edge-on, and the drawing
is the plan.

A sketch that is not such an outline is refused, with the reason, rather than
approximated: two outlines (``has 2 faces``), a hole in one (a column nobody
said how to draw), an open one, a spline (``edge 3 of ... is a B-spline``), or
one that is not on the XY plane.

``sketch:`` and ``height:`` may be ``%...%`` expressions over the scene's
parameters, and PartCAD ships one such scene, ``//builtin/building:room``, with
the parameters ``sketch`` and ``height``. Any package can use it without
declaring a scene of its own -- by name, or through an ``enrich``. Name the
sketch in full, because it belongs to your package and not to ``//builtin``:

.. code-block:: yaml

  scenes:
    living-room:
      type: enrich
      source: //builtin/building:room
      with:
        sketch: //my/apartment:living-room-plan
        height: 2600

``wall:`` names the part each wall is, ``//builtin/building:wall`` unless it says
otherwise. Whatever it names is asked for with the parameters ``length``,
``height`` and ``radius`` (see :ref:`walls`), so a wall of your own -- another
colour, say -- is an ``enrich`` of that one, or a ``type: wall`` part declaring
the same three parameters.

A room is a scene, so it is not manufacturable, and its walls are not either:
see :ref:`walls` for what that excuses them from in ``pc test``.

Scene types a plugin adds
=========================
Beside ``assy`` and ``walls``, a scene may be declared in a format an :doc:`import plugin
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
