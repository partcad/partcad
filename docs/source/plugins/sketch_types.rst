############
Sketch types
############

A **sketch type plugin** teaches PartCAD how to build a sketch, the way a
:doc:`part type </plugins/part_types>` teaches it how to build a part. The
types PartCAD implements itself -- ``basic``, ``dxf``, ``svg``, ``build123d``,
``cadquery`` and the rest of :ref:`the list <sketches>` -- are what a sketch's
``type:`` normally names. A ``sketchTypes:`` section declares one more,
belonging to the package that writes it, and sketches then name that instead.

It is worth doing for the same reasons a part type is: **a family of profiles
produced the same way every time** -- a profile system, a gasket generator, a
2D kernel PartCAD does not know about, a file format PartCAD cannot read --
where the difference between one sketch and the next is a handful of
parameters or a file, not a script each.

Using one
=========

A ``type:`` beginning with ``:`` names a sketch type of the sketch's own
package and is expanded to ``<package path>:<name>`` when the package loads.
Write the package path out to use another package's, including one a
:doc:`repository plugin </plugins/repositories>` serves:

.. code-block:: yaml

  dependencies:
    profiles:
      type: git
      url: https://example.com/partcad-profiles

  sketches:
    gasket:
      type: profiles:gasket      # a sketch type from the imported package
      parameters:
        width: 40
        holes: 4

  parts:
    gasket_3mm:
      type: extrude
      sketch: gasket
      depth: 3

A sketch built this way is an ordinary sketch in every other respect: it
renders, exports, is extruded and swept. A sketch type is listed like any other
object of its package but **is never a shape in its own right**, and it keeps
a namespace of its own, as a part type does: a sketch may share its type's
name.

Writing one
===========

.. code-block:: yaml

  sketchTypes:
    plate:
      kind: wrapper              # the default, and currently the only kind
      path: plate.py             # "<name>.py" if left out
      desc: A rounded plate with a row of holes
      pythonRequirements:        # what this script's sandbox needs, beyond build123d and OCP
        - numpy==2.3.4

  sketches:
    plate:
      type: ":plate"
      parameters:
        width:
          type: float
          default: 40

A ``sketchTypes:`` entry takes the keys a ``partTypes:`` entry does, with the
same meanings: ``kind``, ``desc``, ``url``, ``unless``, ``path``,
``extension``, ``dockerImage``, ``container``, ``reportsDependencies`` and
``pythonRequirements``. With ``container:`` the script runs in that image as it
is, instead of in a Python sandbox, exactly as a part type's does -- what the image
needs, how the sketch's file and ``request["cache_dir"]`` reach it, and what the
sketch is cached under are in :ref:`part-type-container`. ``requireSolid`` is a part's only, and there is no
sketch counterpart of it: no sketch type of PartCAD's holds its sketches to
being closed or planar -- a DXF of bend lines is open, a sweep path is a wire --
so what a sketch must be is said by what uses it (an extrusion wants faces).

What the script is handed
-------------------------

The script runs in the sandbox once per sketch -- it is executed, not imported,
under the run name ``__partcad_sketch__`` -- with a ``request`` dictionary in its
globals:

``request["kind"]``
  ``"sketch"`` (a part type's script is handed ``"part"``).
``request["name"]``, ``request["label"]``, ``request["orig_name"]``
  The sketch's full name (``<package>:<name>``), its name, and the name it was
  declared under.
``request["parameters"]``
  The sketch's ``parameters``, each resolved to its value: the declaration's
  ``default``, or what a reference to the sketch set it to.
``request["config"]``
  The sketch's whole declaration, so a sketch may carry fields of the type's own
  (``type:`` and the keys above are PartCAD's; anything else is passed on).
``request["cache_dir"]``
  A directory belonging to the package that declares the type, for what the
  script downloads or builds once and keeps -- a converter, a compiled tool.
``request["path"]``
  For a type that declares an ``extension`` only: the absolute path of the
  file the sketch is read from -- the sketch's ``path``, relative to the
  sketch's own package, or ``<sketch name>.<extension>`` beside its
  ``partcad.yaml``, fetched first if the sketch says ``fileFrom: url``. The
  file, and every file in the sketch's ``dependencies:``, is what the sketch's
  cache entry is keyed on.

What the script hands back
--------------------------

The script leaves its result in a global ``output``:

.. code-block:: python

  output = {"shape": shape}                 # one shape, or
  output = {"shapes": [shape, ...]}         # several (lists may nest), or
  output = {"exception": "what went wrong"} # a failure, reported against the sketch

A shape is an OCP ``TopoDS_Shape`` or anything that holds one in its
``wrapped`` attribute, so build123d objects are handed back as they are. A
sketch is made of **faces, wires and edges**, and those are what may be handed
back -- or compounds and shells of them, which are taken apart:

- **A region with holes** is one face whose holes are its inner wires: what
  ``BRepBuilderAPI_MakeFace`` builds when the hole's wires are added to it, and
  what a build123d ``Rectangle(...) - Circle(...)`` is.
- **An open curve** is a wire, or a single edge.
- **Lines, arcs and Bezier or B-spline curves** keep their exact geometry: a
  sketch is a boundary representation, so a circle stays a circle when it is
  extruded, rendered or exported to DXF, rather than becoming a polygon.

Draw in the **XY plane**: that is the plane ``extrude`` extrudes from, along
+Z, and the one ``pc render`` projects a sketch onto. Each shape handed back is
one of the sketch's components; all of them together are the sketch. A solid
among them fails the sketch rather than being dropped, as does handing back
nothing.

A script whose type says ``reportsDependencies: true`` may also say which files
it read beyond ``request["path"]``, so that the sketch is built again when one
of them changes -- ``output["dependencies"] = ["other.dat", ...]``, each
absolute or relative to the directory of ``request["path"]``; ``None`` if it
cannot tell, and the sketch is then not cached.

Why shapes, and not a file
~~~~~~~~~~~~~~~~~~~~~~~~~~

The answer is the geometry itself rather than an SVG or a DXF the script wrote
for PartCAD to read back, because a file format is the lossy half of the
journey: an SVG has no holes as such, only fill rules, and either format says
what units its numbers are in in its own way. Shapes are what every other sketch
type hands back, and what a sketch is. A script that has a file -- a tool that
writes SVG or DXF -- reads it itself, with what the sandbox already has:

.. code-block:: python

  if __name__ == "__partcad_sketch__":
      import subprocess
      from build123d import import_svg

      svg = request["cache_dir"] + "/profile.svg"
      subprocess.run(["profile-tool", "--out", svg], check=True)
      output = {"shapes": list(import_svg(svg, flip_y=False))}

``CACHE_VERSION``
-----------------

A sketch built by a sketch type is cached like any other, keyed on the version
the script reports as well as on the sketch's own configuration -- a
module-level ``CACHE_VERSION = <int>``, read **without running the script**.
Raise it whenever a change to the script changes the sketches it builds.
A sketch type a repository plugin serves is keyed on the plugin's version
instead.

An example
==========

``examples/produce_sketch_wrapper`` declares one sketch type and two sketches
built with it, each setting the type's parameters to its own values:

.. code-block:: yaml

  sketchTypes:
    plate:
      kind: wrapper
      path: plate.py

  sketches:
    plate:
      type: ":plate"
      parameters:
        width: {type: float, default: 40}
        height: {type: float, default: 20}
        holes: {type: int, default: 2}

``plate.py`` hands back a face with holes and an open wire made of a line and
an arc:

.. code-block:: python

  CACHE_VERSION = 1

  if __name__ == "__partcad_sketch__":
      from build123d import Circle, Line, Pos, RectangleRounded, ThreePointArc, Wire

      parameters = request["parameters"]
      width = float(parameters.get("width", 40))
      height = float(parameters.get("height", 20))
      holes = max(0, int(parameters.get("holes", 2)))

      plate = RectangleRounded(width, height, height / 4)
      pitch = width / (holes + 1)
      for index in range(holes):
          plate -= Pos(-width / 2 + pitch * (index + 1), 0) * Circle(height / 8)

      y = height / 2 + 5
      bend = Wire([
          Line((-width / 2, y), (0, y)),
          ThreePointArc((0, y), (width / 4, y + 5), (width / 2, y)),
      ])
      output = {"shapes": [plate, bend]}

From that directory:

.. code-block:: shell

  pc render -t svg plate     # a drawing of it, like any other sketch
  pc ide view -s plate       # or in the Digital Thread
