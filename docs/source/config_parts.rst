#####
Parts
#####

.. _parts:

=====
Parts
=====

Parts are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <scad|cadquery|build123d|chili3d|sdf|step|brep|stl|3mf|obj|extrude|sweep
             |kicad|compound|alias|enrich|:<partType declared by this package>>
      desc: <(optional) textual description>
      images: <(optional) the images this part was modeled from; see below>
      path: <(optional) the source file path, "{part name}.{ext}" otherwise>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      # ... type-specific options ...
      offset: <(optional) OCCT Location object, e.g. "[[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]">

      # The below syntax is similar to the one used for interfaces,
      # with the only exception being the word "implements" instead of "inherits".
      implements: # (optional) the list of interfaces to implement
        <interface name>: <instance name>
        <other interface name>: # instance name is implied to be be empty ("")
        <yet another interface>:
          <instance name>: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
      # (optional) new names for ports and interface instances this part has:
      # for an enrich or an alias, those of what it points at. See
      # "New names for what an object has" under assemblies.
      map:
        <new port name>: [<port>]
        <new name>:
          port: <port>   # or interface: <interface> and instance: <instance>
          moveX: <(optional) mm>
          turnZ: <(optional) degrees>
      ports: # (optional) the list of ports in addition to the inherited ones
        <port name>: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
        <other port name>: # [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle] is implied
        <another port name>:
          location: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
          sketch: <(optional) name of the sketch used for visualization>

      # What the shape this part produces reports about itself. See "Properties".
      properties: # (optional)
        material: <(optional) the name of the material this shape is made of>
        color: <(optional) "#RRGGBB" or "#RRGGBBAA">

        physics: # (optional) physical properties
          mass: ... # kg
          density: ... # kg/m^3, what the mass is computed from if 'mass' is not stated
          centerOfMass: [<x>, <y>, <z>] # mm, in the shape's own frame
          inertiaOrientation: [<roll>, <pitch>, <yaw>] # (optional) degrees
          inertia: # kg*m^2, about 'centerOfMass'
            ixx: ...
            ixy: ...
            ixz: ...
            iyy: ...
            iyz: ...
            izz: ...
          friction: ...        # coefficient, along 'frictionDirection'
          friction2: ...       # coefficient, across it
          frictionDirection: [<x>, <y>, <z>]
          contactStiffness: ... # N/m
          contactDamping: ...   # N*s/m
          minContactDepth: ...  # mm
          maxContactVelocity: ... # mm/s
          restitution: ...     # 0 is a dead stop, 1 a perfect bounce
          maxContacts: ...
          velocityDamping: ...
          selfCollide: <true|false>
          gravity: <true|false>

      # What this part contributes to every connection it takes part in.
      connect: # (optional)
        hold: <(optional) name of an interface, or the list of them, to hold this part by>
        holdInstance: <(optional) instance of each interface listed in "hold", in the same order>
        holdForceMin: <(optional) least force to hold this part with, in N, default: 3>
        holdForceMax: <(optional) most force to hold this part with, in N, default: 7>
        holdForce: <(optional) sets both "holdForceMin" and "holdForceMax">

Depending on the type of the part, the configuration may have different options.

``multiConnect`` says whether one instance of an interface may take more than
one object. It is ``false`` by default, because most joints are made once: a
stud takes one brick, a bolt hole takes one bolt, and two objects connected to
the same instance is a mistake ``pc test`` reports. Set it on the joints that
are not made once - a shaft carrying several parts along its length, a rail, a
bus bar:

.. code-block:: yaml

  interfaces:
    shaft:
      multiConnect: true

The ``threadStep``, ``selfScrew`` and ``multiConnect`` fields of an interface are inherited by the
interfaces that inherit it, and by the connections made through it. Two
interfaces that are connected have to agree on their thread unless one of them
cuts its own. See :doc:`assy`.

The fields of the ``connect`` section are the defaults for the ``holdWith*`` and
``holdTo*`` fields of the ``how`` section of an Assembly YAML
``connect``/``connectPorts`` node. See :doc:`assy`.

``images`` names the pictures a part was modeled from -- a technical drawing, a
photograph, a sketch -- as paths relative to the package. They are what
``pc render -t readme`` puts beside the part, next to its own rendered image, so
that a reader of the README sees what the model was made to match. Assemblies,
sketches and interfaces take the same field, and it says nothing about how the
object is built: nothing reads these images but the README.

The ``properties`` section says what the shape this part produces is, as opposed
to ``parameters``, which say what is asked of the type that produces it. See
:ref:`properties` below.

See :ref:`location` for more information on the OCCT Location object.

CAD Scripts
-----------

Define parts with CodeCAD scripts using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <scad|cadquery|build123d|chili3d|sdf>
      cwd: <alternative current working directory>
      showObject: <(optional) the name of the object to show using "show_object(...)">
      patch:
        # ...regexp substitutions to apply...
        "pattern": "repl"
      pythonRequirements: <(python scripts only) the list of dependencies to install>
      javascriptRequirements: <(JavaScript scripts only) the list of npm dependencies to install>
      javascriptVersion: <(JavaScript scripts only) Node.js major version, overriding the package's>
      chili3dVersion: <(Chili3D parts only) the version of Chili3D, overriding the package's>
      dependencies: # (optional) the list of filenames the caching logic checks for changes
        - <file1.py>
        - <file2.dat>
      parameters:
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

+--------------------------------------------------------------------------------------+---------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Example                                                                              | Configuration             | Result                                                                                                                  |
+======================================================================================+===========================+=========================================================================================================================+
|                                                                                      | .. code-block:: yaml      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_cadquery_primitive/cylinder.svg?raw=true  |
|| `CadQuery <https://github.com/CadQuery/cadquery>`_ or                               |                           |   :width: 128                                                                                                           |
|| `build123d <https://github.com/gumyr/build123d>`_ script                            |   parts:                  |                                                                                                                         |
|| in ``src/cylinder.py``                                                              |     src/cylinder:         |                                                                                                                         |
|                                                                                      |       type: cadquery      |                                                                                                                         |
|                                                                                      |       # type: build123d   |                                                                                                                         |
+--------------------------------------------------------------------------------------+---------------------------+-------------------------------------------------------------------------------------------------------------------------+
|| `OpenSCAD <https://en.wikipedia.org/wiki/OpenSCAD>`_ script                         | .. code-block:: yaml      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_openscad/cube.svg?raw=true                |
|| in ``cube.scad``                                                                    |                           |   :width: 128                                                                                                           |
|                                                                                      |   parts:                  |                                                                                                                         |
|                                                                                      |     cube:                 |                                                                                                                         |
|                                                                                      |       type: scad          |                                                                                                                         |
+--------------------------------------------------------------------------------------+---------------------------+-------------------------------------------------------------------------------------------------------------------------+

Chili3D scripts
^^^^^^^^^^^^^^^

`Chili3D <https://github.com/xiangechen/chili3d>`_ scripts are JavaScript, not
Python, and live in ``.chili`` files:

.. code-block:: yaml

  parts:
    cube:
      type: chili3d

A ``.chili`` file is an ES module. PartCAD runs it in a sandboxed Node.js with
the Chili3D API already loaded, and takes whatever the script hands back as the
part. These are available as globals:

``chili3d``
  the Chili3D module namespace (``Plane``, ``XYZ``, ...)

``shapeFactory``
  a ready-made ``new chili3d.ShapeFactory()``

``wasm``
  the OCCT WebAssembly kernel, for what the high-level API does not cover

``show(...)``
  declare a shape (or an array of them) to be the part's result

``show_object(...)``
  an alias of ``show``, so a script reads like its CadQuery counterpart

``parameters``
  the part's build parameters, also injected as globals by name

.. code-block:: javascript

  const { Plane, XYZ } = chili3d;

  const box = shapeFactory.box(Plane.XY, 10, 10, 10).value;
  const hole = shapeFactory.cylinder(XYZ.unitZ, new XYZ(5, 5, 0), 3, 10).value;

  show(shapeFactory.booleanCut([box], [hole]).value);

A script that does not call ``show()`` may instead export its result as
``default``, ``shape``, ``result`` or ``part``. Either way the shape may be a
raw ``TopoDS_Shape``, the ``Result`` the Chili3D API returns, or the ``IShape``
inside it - PartCAD unwraps all of them, and reports the error a failed
``Result`` carries rather than producing an empty part.

The script is evaluated inside the PartCAD sandbox, so ``import`` works the way
it does in any Node.js project: by name for anything the package declares under
``javascriptRequirements``, and relative for a file next to the script.

.. code-block:: yaml

  javascriptRequirements:
    - "seedrandom@3.0.5"

Choosing versions
~~~~~~~~~~~~~~~~~

``javascriptVersion`` names the Node.js major version to render on, and
``chili3dVersion`` the version of Chili3D to render with. Both may be set on the
package and overridden on an individual part:

.. code-block:: yaml

  javascriptVersion: "22"
  chili3dVersion: "1.1.2"

  parts:
    cube:
      type: chili3d
    older_cube:
      type: chili3d
      chili3dVersion: "1.0.20"

``chili3dVersion`` takes an exact version, or any range or tag npm accepts
(``"^1.1"``, ``"latest"``). Naming ``chili3d`` under ``javascriptRequirements``
does the same thing; where both are given the dedicated option wins, and a
part's choice wins over its package's. Note that not every Chili3D release
publishes the WebAssembly kernel PartCAD needs - one that does not fails with a
message naming the version.

Unlike the Python script types, where PartCAD pins CadQuery and build123d and
overrides a package that asks for a different version, this really is the
package's choice. A Node.js sandbox is identified by the set of dependencies it
holds, so a package on its own Chili3D gets an environment of its own and
changes nothing for any other package - or for another part of the same one.

Two notes on how this differs from the Python script types:

* ``patch`` expressions are JavaScript regular expressions rather than Python
  ones. The syntax is nearly identical, but the replacement follows JavaScript's
  rules: a capture group is referenced as ``$1`` where Python would write
  ``\1``, and a literal dollar sign is written ``$$``.
* Chili3D is an input format only. A part can be *defined* by a ``.chili``
  script and then exported to STEP, STL, 3MF and everything else PartCAD
  writes, but no exporter produces a ``.chili`` file.

CAD Files
---------

Define parts with CAD files using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <step|brep|stl|3mf|obj>
      binary: <(stl only) use the binary format>

A CAD file published elsewhere (in a vendor's catalog, for example) does not
have to be committed to the package: see :ref:`files` for how to have PartCAD
download it on demand.

+--------------------------------------------------------------------------------------+---------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Example                                                                              | Configuration             | Result                                                                                                                  |
+======================================================================================+===========================+=========================================================================================================================+
|| CAD file                                                                            | .. code-block:: yaml      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_step/bolt.svg?raw=true                    |
|| (`STEP <https://en.wikipedia.org/wiki/ISO_10303>`_ in ``screw.step``,               |                           |   :width: 128                                                                                                           |
|| `STL <https://en.wikipedia.org/wiki/STL_(file_format)>`_ in ``screw.stl``,          |   parts:                  |                                                                                                                         |
|| or `3MF <https://en.wikipedia.org/wiki/3D_Manufacturing_Format>`_ in ``screw.3mf``) |     screw:                |                                                                                                                         |
|                                                                                      |       type: step          |                                                                                                                         |
|                                                                                      |       # type: stl         |                                                                                                                         |
|                                                                                      |       # type: brep        |                                                                                                                         |
|                                                                                      |       # type: 3mf         |                                                                                                                         |
|                                                                                      |       # type: obj         |                                                                                                                         |
+--------------------------------------------------------------------------------------+---------------------------+-------------------------------------------------------------------------------------------------------------------------+

.. _extrude:

Extrude
-------

Define parts by extruding a sketch using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: extrude
      sketch: <name of the sketch to extrude>
      depth: <depth of the extrusion>

+---------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Example                   | Result                                                                                                                  |
+===========================+=========================================================================================================================+
| .. code-block:: yaml      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_extrude/dxf.svg?raw=true                  |
|                           |   :height: 256                                                                                                          |
|   parts:                  |                                                                                                                         |
|     dxf:                  |                                                                                                                         |
|       type: extrude       |                                                                                                                         |
|       sketch: dxf_01      |                                                                                                                         |
|       depth: 10           |                                                                                                                         |
+---------------------------+-------------------------------------------------------------------------------------------------------------------------+

.. _sweep:

Sweep
-----

Define parts by sweeping a sketch using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: sweep
      sketch: <name of the sketch to sweep>
      axis: [[0, 0, 10], [10, 0, 0]] # the sweep path defined as a list of vectors
      ratio: <(optional, >0.5, <1.0) the placement of additional points along the vectors for better approximation>

+---------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Example                                                                   | Result                                                                                                                  |
+===========================================================================+=========================================================================================================================+
| .. code-block:: yaml                                                      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_sweep/pipe.svg?raw=true                   |
|                                                                           |   :height: 256                                                                                                          |
|   parts:                                                                  |                                                                                                                         |
|     pipe:                                                                 |                                                                                                                         |
|       type: sweep                                                         |                                                                                                                         |
|       sketch: section                                                     |                                                                                                                         |
|       axis: [[0, 0, 20], [0, 0, 20], [20, 0, 0], [20, 20, 0], [0, 20, 0]] |                                                                                                                         |
+---------------------------------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+

References
----------

It is also possible to declare new parts by referencing other parts that are
already defined elsewhere.

.. list-table::
  :header-rows: 1
  :widths: 10 50 40

  * - Method
    - Configuration
    - Description
  * - Alias
    - .. code-block:: yaml

        parts:
          <alias-name>:
            type: alias
            source: </path/to:existing-part>
    - Create a shallow clone of the existing part. For example, to make it
      easier to reference it locally.
  * - Enrich
    - .. code-block:: yaml

        parts:
          <enriched-part-name>:
            type: enrich
            source: </path/to:existing-part>
            with:
              <param1>: <value1>
              <param2>: <value2>
            offset: <OCCT-Location-obj>
    - Create an opinionated alternative to the existing part by initializing
      some of its parameters, and overriding any of its properties. For
      example, to avoid passing the same set of parameters many times.

Both are references rather than parts of their own. An ``enrich`` resolves to
the *instance* of the object it points at that has the values it asks for --
the same object PartCAD produces for ``<name>;<param>=<value>`` -- so that
instance belongs to the package declaring the source, and one instance serves
every enrich, in any package, that asks for the same values. An ``alias``
resolves to the object itself.

That is also what the shape cache is keyed on: a reference takes the key of
what it points at, so the geometry is stored once however many references lead
to it rather than once per reference. A reference that moves or scales what it
points at hands back different geometry and so keys differently -- on the
source's key, plus what it adds.

Because asking for a value is asking for the instance that has it, and an
instance is named ``<name>;<param>=<value>,...``, a ``with:`` value may not
contain ``,``, ``;`` or ``=``: such a value could not be named. The same holds
for what a parameter declares as its ``default:`` or offers in its ``enum:``.

An enrich says which values it wants, and nothing about how the object is
built. ``path``, the requirements, the sandbox versions, the inputs of the
types that build one object out of another -- and ``parameters:``, which
``with:`` is the way to state -- belong to the declaration of the object
itself. Declaring one of them on an enrich is reported as ignored, and the
object it produces is the one it would have produced without it.

Both are available for :ref:`sketches` and :ref:`assemblies` too, spelled the
same way.

.. _part-types:

Part types the package defines itself
-------------------------------------

The types above are the ones PartCAD implements. A package can also declare a
type of its own, in a ``partTypes`` section, and then build parts with it. This
is worth doing when a family of parts is produced the same way every time --
generated from a table, fetched from a catalogue, built by a modelling helper
the package already has -- and the difference between them is a handful of
parameters rather than a script each.

.. code-block:: yaml

  partTypes:
    box:
      kind: wrapper
      path: box_wrapper.py

  parts:
    demo:
      type: ":box"
      parameters:
        size:
          type: float
          default: 12

``kind`` is ``wrapper``, which is the default and currently the only kind. Its
``path`` (``<name>.py`` if left out) is a Python script that PartCAD runs in the
sandbox once per part, with the part's ``request`` in its globals -- the
resolved ``parameters`` among them -- and which leaves the geometry in a global
``output``:

.. code-block:: python

  if __name__ == "__partcad_part__":
      from build123d import Box

      size = float(request["parameters"].get("size", 10))
      output = {"shape": Box(size, size, size).wrapped}

Because the script runs in a sandbox it may import OCP, build123d or CadQuery;
``pythonRequirements`` on the ``partType`` says what that sandbox needs, exactly
as it does for a package. This is the same mechanism as a custom output
implementation (see :ref:`output-files`), pointed at building a shape rather
than writing a file.

A ``type`` beginning with ``:`` names a ``partType`` of the part's own package
and is expanded to ``<package path>:<name>`` when the package is loaded. Write
the package path out to use another package's type, which is what makes these
shareable: a package that declares a ``partType`` is a package other people can
import and build parts with. A ``partType`` is listed like any other object but
is never a shape in its own right -- it is how parts are made, not one of them.

See ``examples/produce_part_wrapper`` for the whole of the example above.

Should PartCAD implement a type natively that you find yourself writing again
and again, please file an issue on GitHub or write to
`support@partcad.org <mailto:support@partcad.org>`_.

.. _parameters:

Parameters
----------

Parameters are **inputs**. They are a request made of the object type that
produces the part - the ``width`` a CadQuery script extrudes to, the
``tolerance`` a mesh is faceted at - and they only mean anything if that type
accepts them. Two parts that differ in a parameter are different shapes, so a
parameter is part of what the shape cache is keyed on.

What comes back out is :ref:`properties`, and the two are not the same thing
even where they share a name: ``parameters.material`` asks for a part to be made
of something, and ``properties.material`` states what the part that came out is
made of.

Most parameters are the part's own invention. A script may call one whatever it
likes, and nothing outside that script knows what it means, so PartCAD lets a
part declare any name it wants. A few are **object-type parameters** instead:
contributed by the part *type* rather than declared out of nothing, with a
meaning PartCAD itself acts on. They are therefore only available on the types
that can honour them. Today there are three - ``material``, ``color`` and
``tolerance``.

What decides which types accept them is whether the part is a single
homogeneous body - one solid, made of one thing - because that is what has to
be true for one ``material:``, one ``color:`` or one ``tolerance:`` to be true
of the whole part. A mesh is one body: an STL file is a surface with nothing
inside it to vary, and the only way it has a material at all is for somebody to
say so. So is a solid built by a script, and so is one extruded from a single
sketch. ``stl``, ``cadquery``, ``build123d``, ``sdf``, ``scad`` and ``extrude``
accept all three.

A STEP file is not one body. It can carry many solids, each already stating a
material and a colour of its own, and naming one for the file would be a claim
about a part the file itself describes better. ``step`` rejects them, and so
does ``kicad``, which is a STEP file behind a footprint. What such a part is
made of belongs under :ref:`properties`, where a shape says what it turned out
to be rather than what was asked of it. How precisely it has to be made is a
separate question and has an answer of its own, below: see
:ref:`tolerance-field`.

Every other part type rejects them too, but for a different reason: whether it
should accept them has not been decided yet, and answering "no" until somebody
decides leaves the question open rather than settling it by accident.

Declaring one of these under ``parameters:`` of a type that does not accept it
is an error, not a warning. It costs the package that one part - the rest of
the package loads and builds as usual - and the command that found it reports a
failure. No other parameter name is restricted anywhere: what is policed is the
handful of names PartCAD gives a meaning to, not the right to declare
parameters. It is the parameter's *name* that is policed, too, and not the
shape of its declaration - any parameter may carry ``color:`` and ``material:``
fields of its own describing what one of its values looks like, whatever the
part type.

``tolerance`` is the one of the three that has a default, ``0.0``: it reads
back as that on any type that accepts it, whether or not a part declares one.
The default is applied when the value is read and is never written into the
part's ``parameters:`` section, because that section is part of what the shape
cache is keyed on - writing a default in would move the cache key of every part
that never mentioned a tolerance, for a value nobody set. A tolerance somebody
did declare keys the cache like any other input, because it is one.

A tolerance of ``0.0`` means nobody said. It reads as a demand for perfect
precision, which is not something a manufacturer can be asked for, so
:doc:`pc test <cli>` fails a part that is going to be *made* and has no
tolerance - including a part reached through an assembly in the package. A part
that is bought rather than made is not asked: it comes as it comes.

A CadQuery or build123d script is handed every parameter the part declares, each
as a variable of the same name, and the script has to assign that name at its
own top level for the value to land anywhere - a parameter the script never
mentions is a parameter nobody will read, so naming one is an error and usually
a typo. Object-type parameters are the one exception, because the part may be
required to declare one the script has no use for: a script that assigns
``material`` still receives the declared material, and a script that does not
mention it is left alone rather than refused. Nothing else is forgiven. An SDF
script takes its parameters differently - they are prepended to it as
assignments - so this never arose there.

Each part may have a list of parameters that are passed into the scripts to
modify the part.
The parameters can be of types ``string``, ``float``, ``int`` and ``bool``.
The parameter values can be restricted by specifying the list of possible values
in ``enum``.
The initial parameter value is set using ``default``.

.. code-block:: yaml

  parts:
    <part name>:
      # ...
      parameters:
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

There are several parameter names that are reserved for values used in
visualization, simulation calculations and, if applicable, manufacturing
(also referred to as **MCFTT parameters** using their first letters):

- ``material``

  Must point at an object of type ``material``, as ``<package>:<name>``.
  Some of them are defined in ``//pub/std/manufacturing/material``; see
  :ref:`materials` for declaring your own.
  This one is an object-type parameter, so it may only be declared on the part
  types listed above.
  When a request is made to a manufacturing API,
  a close enough material is selected from the materials provided by the
  manufacturer. The responsibility to select the right material is on the
  implementation of the manufacturing API (the ``provider`` object in PartCAD).

- ``color``

  This one is an object-type parameter too, with the same restriction.

  **Not implemented yet. Use color names for now.**

- ``finish``

  Optional. Can be omitted for no finish.

  **Not implemented yet.**

- ``texture``

  Optional. Can be omitted for no texture.

  **Not implemented yet.**

- ``tolerance``

  An object-type parameter as well, and the one with a default: omitting it is
  the same as writing ``0.0``, which is a claim to perfect precision and is
  what ``pc test`` rejects on a part that is to be manufactured. Give it a real
  value on anything you intend to have made.

  ``step`` and ``kicad`` parts state this as a ``tolerance:`` field instead of
  as a parameter, and their file may state it for them; see
  :ref:`tolerance-field`.

If the part has variable MCFTT parameters depending on the surface,
then either this part must be broken down into multiple parts,
or the values must be derived from CAD files/scripts (not implemented yet).
In the latter case the part will not be eligible for manufacturing features,
unless a specific manufacturing service provider recognizes (vendor,SKU) values
and have received corresponding manufacturing instructions out-of-band.

The MCFTT parameters are not required and have no impact on parts that have
``vendor`` and ``sku`` set and that are procured using providers of the type
``store``.

The MCFTT parameters are a request, and the request is a manufacturing one: they
say what the part should be made of, and how well, for the provider that will
make it. They are not a claim about a shape that exists. A part read from a STEP
file that already states its material does not answer them, and the answer is
not what an exporter writes into a file. That is :ref:`properties`, below.

.. _tolerance-field:

Tolerance on the types that state it in the file
------------------------------------------------

``step`` and ``kicad`` reject the ``tolerance`` *parameter*, for the reason
above, which would leave them with no way to say how precisely a part has to be
made and nothing to answer :doc:`pc test <cli>` with. They have one, because a
STEP file has somewhere of its own to say it: AP242 carries the whole of GD&T -
a plus/minus tolerance on a dimension, a flatness or a position tolerance on a
feature - so PartCAD reads the file.

Plenty of STEP files carry none of it. For them - and only on the types whose
file could have carried it - the part declaration takes a ``tolerance:``
**field** of its own:

.. code-block:: yaml

  parts:
    bracket:
      type: step
      tolerance: 0.1   # millimetres

It is a field rather than a parameter because it asks nothing of the type that
produces the shape: the file is read the same way whether or not it is there,
and nothing is built differently for it. It is accepted only on the types that
take it; declaring it anywhere else is the same per-object error that declaring
a rejected parameter is, and says ``field`` rather than ``parameter`` so that
the two are not confused. An ``alias`` or an ``enrich`` may carry it and
ignores it, like everything else it carries that describes how its source is
built.

There are then three places a part's tolerance can come from, and PartCAD reads
them in this order:

1. The ``tolerance:`` field, where the type takes one. It outranks the file: it
   is written precisely because the file did not say, and a file that later
   starts saying something else is a change to look at rather than one to adopt
   silently.
2. What the file itself states. A file that states one tolerance answers with
   it, whatever unit it is written in - a file in inches is read as inches.
3. The ``tolerance`` parameter, for the homogeneous types that accept it, with
   its default of ``0.0``.

A file that tolerances several features differently has no single tolerance, and
PartCAD does not invent one: the tightest overstates what most of the part
needs, the loosest understates what one of its features does, and an average is
true of nothing. It reads back as ``NaN`` instead, which means *tolerated,
feature by feature* - and ``pc test`` accepts it. Such a part does say how
precisely it has to be made, in more detail than one number holds, and the file
is what goes to the manufacturer.

What ``pc test`` rejects is still only a part that could have said and did not:
``0.0`` on a type that takes the field or the parameter. A part whose type takes
neither and whose file states nothing is reported differently again, naming the
type - that is a fact about the part type rather than about the declaration.

The geometric uncertainty every STEP file carries
(``UNCERTAINTY_MEASURE_WITH_UNIT``, typically ``1e-07`` mm) is deliberately not
read. It is the precision the geometry was written to, not a tolerance anybody
is being held to, and reading it would give every STEP file ever exported a
manufacturing tolerance no shop can work to.

.. _properties:

Properties
----------

Properties are **outputs**. They are what instantiating the object produced -
what the resulting shape reports about itself - and they are declared where the
shape cannot report them on its own. A mesh has no material and no mass, so the
only way a part read from an STL has either is to say so; a URDF import fills
this section in from what the file already stated.

.. code-block:: yaml

  parts:
    <part name>:
      # ...
      properties:
        material: <(optional) the name of the material this shape is made of>
        color: <(optional) "#RRGGBB" or "#RRGGBBAA">
        physics: # (optional)
          mass: ... # kg
          # ... see the full list under "Parts" above

Assemblies take the same section. Nothing in it takes part in the shape cache -
it says nothing about the geometry - which also means nothing notices when an
edit to the CAD invalidates it. It does travel with the shape: a property
declared on a part is carried on the shape that part produces, through the cache
and through every assembly that embeds it, so an export of a whole robot finds
each link's properties on the link. That is also where the properties inherit
the caching a name and a placement already have: an object's own are stamped on
from its configuration every time it is read, but the ones on the parts *inside*
a cached assembly are part of that assembly's cached tree, and editing them does
not invalidate it any more than renaming a part does. ``pc system reset``, or a
change to something the assembly does hash, is what picks them up.

Every ``physics`` property has a PartCAD name and a PartCAD unit, and the set of
them is closed. Lengths are millimetres and angles degrees, as everywhere else
in PartCAD; everything else is SI, so a mass is kilograms, a density kg/m³ and
an inertia tensor kg·m². Nothing is stored under the name of the format it came
from: a URDF import reads ``<inertial>`` and the friction and contact settings
of a ``<gazebo>`` block into these properties one value at a time, and a URDF
export writes each of them back into the element that states it. A URDF that
says something PartCAD has no property for stops the import instead of being
carried opaquely, and a property PartCAD holds that URDF cannot state is
reported when it is exported. See :doc:`simulation`.

Most parts state none of these, and have most of them all the same. A shape
made of a :ref:`material <materials>` has the material's ``mu`` as its
``friction`` and the material's ``density`` as its ``density`` -- the same unit,
so nothing is converted -- and a shape with a solid in it has a mass, a centre
of mass and an inertia: its solid at that density. PartCAD works these out in
one order, everywhere:

=================  ==========================================================
property           where it comes from, first one that applies
=================  ==========================================================
``density``        stated; else the material's; else, for an export only, the
                   export's ``density`` parameter, else 2700 kg/m³
``mass``           stated; else the volume at that density
``centerOfMass``   stated; else the centroid of the solid
``inertia``        stated; else the solid's, scaled to the mass above
``friction``       stated; else the material's ``mu``
=================  ==========================================================

So a part that states its mass and nothing else still turns the way its solid
says it does, at the weight it says it is; and the centre of mass and the
inertia come from the same density as the mass, so the three agree. A part
that states no density and is made of nothing that does has no known mass, and
``pc info`` says so rather than inventing one; an export weighs it at the
export's ``density`` parameter, or at aluminium's 2700 kg/m³, because a
simulator handed a body with no mass makes one up regardless.

``pc info`` reports all of this as ``MassProperties`` -- each value with its
unit and where it came from -- and an assembly's as its parts' added up in its
own frame. A part's values are cached, and go stale exactly when they should:
the entry is keyed on the part's own cache key, so an edit to its CAD is a new
one, and on what the derivation reads besides the geometry -- the density and
where it came from, and the values the part states -- so an edit to its
material's density, or to its stated mass, is a new one too, and an edit to
anything else is not. See :doc:`simulation`.

A file type that has a way to state these declares ``properties: true`` in its
``export:`` section, and is handed them keyed by the full name of the shape they
belong to -- already worked out in the order above, so that an exporter writes
a mass and never computes one. URDF is the one built-in format that does.
