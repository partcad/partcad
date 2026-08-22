Configuration
#############

Most users need to create a single package, containing one or more parts, and maybe an assembly.
That is achieved by creating a configuration file (``partcad.yaml``) that defines the package and
declares all parts and assemblies it contains.
PartCAD aims to maintain three ways to manage the configuration files:

- Manual configuration file edits.

  PartCAD aims to maintain a simple and intuitive syntax for configuration files.
  It is currently expected that PartCAD users edit the configuration file manually
  immediately or after a few hours of using PartCAD, as the other ways to maintain
  the configuration files are not mature enough yet to meet the needs of advanced users.

- Command line interface.

  PartCAD aims to provide a command line interface for all possible configuration changes
  to any section or field.
  However, there is currently a very limited set of commands implemented: mostly the very
  first operations a new PartCAD user would need.

- Graphical user interface.

  PartCAD aims to provide a Visual Studio Code plugin with a graphical interface to
  allow changes to any configuration file sections or fields.
  However, there is currently a very limited set of operations implemented: mostly the very
  first operations a new PartCAD user would need.

The complete syntax of configuration files is described below.

.. _packages:

========
Packages
========

The package is defined using the configuration file ``partcad.yaml`` placed
in the package folder.
Besides the package properties and, optionally, a list of imported dependencies,
``partcad.yaml`` declares a list of :ref:`objects` contained in this package.


.. code-block:: yaml

  name: <(optional) the package path this package expects to be seen at; see "The package name" below>
  desc: <(optional) description>
  private: <(optional) boolean flag to mark the package as private>
  url: <(optional) package or maintainer's url>
  poc: <(optional) point of contact, maintainer's email>
  partcad: <(optional) required PartCAD version spec string>
  pythonVersion: <(optional) python version for sandboxing if applicable>
  pythonRequirements: <(python scripts only) the list of dependencies to install>
  javascriptVersion: <(optional) Node.js major version for sandboxing if applicable>
  javascriptRequirements: <(JavaScript scripts only) the list of npm dependencies to install>
  chili3dVersion: <(Chili3D parts only) the version of Chili3D to render with>

  dependencies:
      <dependency-name>:
          desc: <(optional) textual description>
          type: <(optional) git|tar|local|external, can be guessed by path or url>
          path: <(local only) relative path to the package>
          url: <(git|tar only) URL of the package>
          relPath: <(git|tar only) relative path within the repository>
          revision: <(git only) the exact revision to import>
          plugin: <(external only) reference to the repository plugin that serves this package>
          subfolder: <(external only) location within the repository, for hierarchies>
          cacheVersion: <(external only) non-negative integer; bump to invalidate the on-disk cache>
          includePaths: <(optional) Jinja2 include path>

  suppliers:
      <(optional) the providers to consider for this package's objects; a bare
       name is one of this package's own, "../sibling:name" is one next door>

  parts:
      <part declarations, see below>

  assemblies:
      <assembly declarations, see below>

  repositories:
      <repository plugin declarations, see below>

The package name
----------------

A package is always addressed by its **location** -- the package path at which
it was loaded, derived from its parent. For example, a package in the
subfolder ``gobilda`` of the package ``//vendor`` is addressed as
``//vendor/gobilda`` regardless of what it declares about itself.

The optional ``name`` field declares the package's **identity**: the package
path at which the package expects to be seen. It only takes effect when the
package is loaded as the root (the top-most package of the current context) --
this lets a package be developed standalone using the very same package path
its consumers will see it at. In every other case ``name`` does not change
where the package is loaded; the location always wins.

This makes it safe to vendor a package -- copy it into your own package tree to
drop a dependency or to follow your own naming convention:

* The vendored copy is loaded at its location in your tree, not at the ``name``
  it declares. If the same package is vendored at two locations (even at two
  different versions), each is an independent instance, addressed at its own
  location, and the two never interact.
* References the package makes to itself using its declared ``name`` are
  automatically redirected to the location where the copy was actually loaded.
  A vendored copy therefore uses itself, instead of silently pulling in another
  copy from the package path it was originally taken from.

As a consequence, a vendored package cannot reference the original copy of
itself by its declared ``name``: that package path always resolves to the local
instance. This is intentional -- referencing two copies of the same package at
once is almost always a mistake, and the alternative would be an implicit,
easily-missed dependency on the upstream package.

============
Dependencies
============

Here are some examples of a dependency declaration in ``partcad.yaml``:

.. role:: raw-html(raw)
    :format: html

+--------------------+-------------------------------------------------------------------------------------------------------+
| Method             | Example                                                                                               |
+====================+=======================================================================================================+
|| Local package     | .. code-block:: yaml                                                                                  |
|| (in the same      |                                                                                                       |
|| source code       |   dependencies:                                                                                       |
|| repository)       |     other_directory:                                                                                  |
|                    |       path: ../../other                                                                               |
+--------------------+-------------------------------------------------------------------------------------------------------+
| GIT repository     | .. code-block:: yaml                                                                                  |
| :raw-html:`<br />` |                                                                                                       |
| (HTTPS, SSH)       |   dependencies:                                                                                       |
|                    |     other_repo:                                                                                       |
|                    |         url: https://github.com/partcad/partcad                                                       |
|                    |         relPath: examples  # where to "cd"                                                            |
+--------------------+-------------------------------------------------------------------------------------------------------+
| Hosted tar ball    | .. code-block:: yaml                                                                                  |
| :raw-html:`<br />` |                                                                                                       |
| (HTTPS)            |   dependencies:                                                                                       |
|                    |     other_archive:                                                                                    |
|                    |       url: https://github.com/partcad/partcad/archive/7544a5a1e3d8909c9ecee9e87b30998c05d090ca.tar.gz |
+--------------------+-------------------------------------------------------------------------------------------------------+

Each dependency becomes a subpackage of the current package. All subfolders of the current package are considered
subpackages (of the type `local`) if they contain a ``partcad.yaml`` file. Subfolders do not need to be explicitly
declared as a dependency, but may be declared to provide a more detailed description.

External packages
-----------------

A dependency of type ``external`` is a package whose contents are served by a
**repository plugin** instead of being read from a folder (``local``) or a
remote archive (``git``, ``tar``). Its ``plugin`` field references a repository
declared in the ``repositories`` section (see :ref:`repositories`):

.. code-block:: yaml

  dependencies:
    example:
      type: external
      plugin: :my_repo    # a repository declared in this package

  repositories:
    my_repo:
      type: basic

The package's objects (parts, sketches, assemblies, ...), its child packages,
and its metadata are all fetched from the plugin on demand, rather than being
enumerated up front. This keeps loading cheap even when the repository is large
or remote: a part is fetched only when it is actually used.

An external package can host a hierarchy. When its children are listed, the
plugin reports child package names; each child is imported as another external
package backed by the same plugin, with a ``subfolder`` that scopes its
requests within the repository. In this way one plugin can serve an entire tree
of packages, each with its own sketches, parts, assemblies, providers and
further children.

Non-null responses from a plugin are cached on disk, keyed by the plugin
reference and the request; a request the plugin has no answer for is remembered
only for the run that made it, and is put to the plugin again after a restart.
The cache does not know when the plugin's code changes, so a plugin that starts
returning a new shape of data (for example, adding a field to every part it
serves) would keep being served the stale, pre-change entries. Set
``cacheVersion`` to a non-negative integer and bump it whenever the plugin's
output format changes: it is folded into the cache location, so bumping it moves
the whole repository (and every child in its hierarchy) to a fresh cache
namespace at once, invalidating the old entries. It defaults to ``0``
(unversioned).

See ``examples/plugin_repository_basic`` (a package backed by a local file),
``examples/plugin_repository_full`` (backed by an HTTP endpoint) and
``examples/plugin_repository_tree`` (a hierarchy of packages).

.. _objects:

=======
Objects
=======

PartCAD :ref:`packages` may contain the following objects:

- :ref:`sketches` are 2D objects that can be used to create 3D objects (e.g. using :ref:`extrude` or :ref:`sweep`),
  but can also be used to aid visualization of :ref:`interfaces` or to provide detailed instructions for AI actors.

- :ref:`interfaces` are abstract objects that describe the endpoint of a connection between parts and provide
  sufficient information to automatically determine the mating of parts.

- :ref:`parts` are 3D objects that are meant to be available for purchase or manufacturing.

- :ref:`assemblies` are instructions how to put parts and other assemblies together to be used as a single object.

- :ref:`providers` are implementations of a way to get parts and assemblies (to purchase them or to manufacture them).

===============
Common Metadata
===============

All :ref:`objects` in PartCAD may carry the following metadata:

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
They are recognized in :ref:`parts`, :ref:`sketches` and :ref:`assemblies`
(an assembly's source file is pulled the same way, whether it is an ``.assy``
file or a CAD file).

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

.. _sketches:

========
Sketches
========

Sketches are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: <basic|dxf|svg|cadquery|build123d>
      desc: <(optional) textual description>
      path: <(optional) the source file path, "{sketch name}.{ext}" otherwise>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      # ... type-specific options ...

Basic
-----

The basic sketches are defined using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: basic
      desc: <(optional) textual description>
      # The below are mutually exclusive options
      circle: <(optional) radius>
      circle:  # alternative syntax
        radius: <radius>
        x: <(optional) x offset>
        y: <(optional) y offset>
      square: <(optional) edge size>
      square:  # alternative syntax
        side: <edge size>
        x: <(optional) x offset>
        y: <(optional) y offset>
      rectangle: <(optional)>
        side-x: <x edge size>
        side-y: <y edge size>
        x: <(optional) x offset>
        y: <(optional) y offset>
      inner: <(optional) inner shape>
        circle: <(optional) radius>
           ...
        square: <(optional) edge size>
           ...
        rectangle: <(optional)>
           ...

There must be only one field ``circle``, ``square`` or ``rectangle`` at the top level of the sketch or in the ``inner`` field.

DXF
---

A sketch can be defined using a `DXF <https://en.wikipedia.org/wiki/AutoCAD_DXF>`_ file.
Such sketches are declared using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: dxf
      desc: <(optional) textual description>
      path: <(optional) filename> # otherwise "<sketch-name>.dxf"
      tolerance: <(optional) tolerance used for merging edges into wires>
      include: <(optional) a layer name or a list of layer names to import>
      exclude: <(optional) a layer name or a list of layer names not to import>

SVG
---

A sketch can be defined using an `SVG <https://en.wikipedia.org/wiki/SVG>`_ file.
Such sketches are declared using the following syntax:

.. code-block:: yaml

  sketches:
    <sketch-name>:
      type: svg
      desc: <(optional) textual description>
      path: <(optional) filename> # otherwise "<sketch-name>.svg"
      use-wires: <(optional) boolean>
      use-faces: <(optional) boolean>
      ignore-visibility: <(optional) boolean>
      flip-y: <(optional) boolean>

CAD Scripts
-----------

See the "CAD Scripts" section in the "Parts" chapter below.

.. _interfaces:

==========
Interfaces
==========

Interfaces are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  interfaces:
    <interface name>:
      abstract: <(optional) whether the interface is abstract>
      desc: <(optional) textual description>
      path: <(optional) the source file path, "{interface name}.{ext}" otherwise>
      threadStep: <(optional) axial distance per full turn of a connection made through this interface, in mm>
      selfScrew: <(optional) whether this interface cuts its own thread instead of matching one>
      inherits: # (optional) the list of other interfaces to inherit from
        <parent interface name>: <instance name>
        <other interface name>: # instance name is implied to be empty ("")
        <yet another interface>:
          <instance name>: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
      ports:  # (optional) the list of ports in addition to the inherited ones
        <port name>: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
        <other port name>: # [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle] is implied
        <another port name>:
          location: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
          sketch: <(optional) name of the sketch used for visualization>
      parameters:
        moveX: # (optional) offset along X
          min: <(optional) min value>
          max: <(optional) max value>
          default: <(optional) default value>
        moveY: [<min>, <max>, <(optional) default>] # alternative syntax
        moveZ: ... # (optional) offset along Z
        turnX: ... # (optional) rotation around X
        turnY: ... # (optional) rotation around Y
        turnZ: ... # (optional) rotation around Z
        <custom parameter name>: # (optional) offset or rotation with an arbitrary direction vector
          min: ...
          max: ...
          default: ...
          type: <move (default)|turn>
          dir: [<x>, <y>, <z>] # the vector to move along or rotate around

Abstract interfaces
-------------------

Abstract interfaces can't be implemented by parts directly.
They also can't be used for mating with other interfaces.
They are a convenience feature so that a property can be implemented once
but inherited multiple times by all child interfaces.

Port visualization
------------------

When a part or an assembly is rendered (in a GUI or when exported to a file),
the ports can be visualized.
When ports are visualized, each port looks like a coordinate system (3D location, direction and rotation)
and, optionally, as a 2D image of an alleged "boundary" (or "siluette") of the port.

It is recommended to define the port boundary at all times.
Here is an example how to define the port boundary using a primitive sketch:

.. code-block:: yaml

  sketches:
    m3:
      type: basic
      circle: 3.0
  interfaces:
    m3:
      ports:
        m3:
          sketch: m3

Here is how it will get visualized:

.. image:: images/interface-m3.png
  :width: 50%
  :align: center

Port matching
-------------

Each port has the coordinates of the logical center of the port and the
direction (orientation) of the port.
Whenever two ports are meant to connect without any offset or angle
(e.g. male and female connectors), their coordinates should match
and their directions should be opposite (rotated 180 degrees around [1, 1, 0]).
The suggested convention is to use the Z-axis (blue) as the main direction.
Male ports should have the Z-axis pointing outwards, while female ports should
have the Z-axis pointing inwards.

Matching multiple ports
-----------------------

Sometimes there are multiple interchangeable ports within one interface.
For example, take a look at the NEMA-17 mounting ports:

.. image:: images/interface-orientation.png
  :width: 50%
  :align: center

It is desired that any mounting port of the motor can be connected to any
mounting port of the bracket.
That can be achieved by orienting the ports in a circular direction.
See how the X-axis (red) is pointing to the next port clockwise (right-hand rule).
If any pair of ports is aligned then all three other port pairs are aligned too.

.. image:: images/interface-orientation-2.png
  :width: 50%
  :align: center

Interface parameters
--------------------

Each interface may declare parameters to allow parametrized mating
(e.g. a slotted hole allows for a mating at an offset within the size of the slot).
There is a list of predefined parameters that are easy to use:

  - moveX, moveY, moveZ: offset along X, Y, and Z axes
  - turnX, turnY, turnZ: rotation around X, Y, and Z axes

.. code-block:: yaml

  interfaces:
    <interface name>:
      parameters:
        moveX: # (optional) offset along X
          min: <(optional) min value>
          max: <(optional) max value>
          default: <(optional) default value>

However custom parameters can be defined to use an arbitrary direction vector
and an arbitrary offset or rotation.

.. code-block:: yaml

  interfaces:
    <interface name>:
      parameters:
        <custom parameter name>:
          min: ...
          max: ...
          default: ...
          type: <move (default)|turn>
          dir: [<x>, <y>, <z>] # the vector to move along or rotate around

When the interface is inherited or used to connect parts, the parameter values
get resolved and applied as inheritance or connection coordinate offsets.

.. code-block:: yaml

  # Interface inheritance with parameters
  interfaces:
    <interface name>:
      # ...
      inherits: # (optional) the list of other interfaces to inherit from
        <parent interface name>:
          <instance name>:
            params:
              moveX: 10

  # Interface implementation with parameters
    parts:
    <part name>:
      # ...
      implements: # (optional) the list of other interfaces to inherit from
        <interface name>:
          <instance name>:
            params: { moveX: 10 }

  # Assembly YAML connection example
  links:
    - part: <target part>
    - part: <source part>
      connect:
        name: <target part>
        toParams:
          turnZ: 1.57

Interface examples
------------------

See the `feature_interfaces` example for more information.

.. _parts:

=====
Parts
=====

Parts are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <openscad|cadquery|build123d|chili3d|sdf|step|brep|stl|3mf|obj|extrude|sweep>
      desc: <(optional) textual description>
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
      ports: # (optional) the list of ports in addition to the inherited ones
        <port name>: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
        <other port name>: # [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle] is implied
        <another port name>:
          location: <OCCT Location object> # e.g. [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]
          sketch: <(optional) name of the sketch used for visualization>

      # What this part contributes to every connection it takes part in.
      connect: # (optional)
        hold: <(optional) name of an interface, or the list of them, to hold this part by>
        holdInstance: <(optional) instance of each interface listed in "hold", in the same order>
        holdForceMin: <(optional) least force to hold this part with, in N, default: 3>
        holdForceMax: <(optional) most force to hold this part with, in N, default: 7>
        holdForce: <(optional) sets both "holdForceMin" and "holdForceMax">

Depending on the type of the part, the configuration may have different options.

The ``threadStep`` and ``selfScrew`` fields of an interface are inherited by the
interfaces that inherit it, and by the connections made through it. Two
interfaces that are connected have to agree on their thread unless one of them
cuts its own. See :doc:`assy`.

The fields of the ``connect`` section are the defaults for the ``holdWith*`` and
``holdTo*`` fields of the ``how`` section of an Assembly YAML
``connect``/``connectPorts`` node. See :doc:`assy`.

See :ref:`location` for more information on the OCCT Location object.

CAD Scripts
-----------

Define parts with CodeCAD scripts using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <openscad|cadquery|build123d|chili3d|sdf>
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

+---------+----------------------------------------+----------------------------+
| Method  | Configuration                          | Description                |
+=========+========================================+============================+
| Alias   | .. code-block:: yaml                   || Create a shallow          |
|         |                                        || clone of the              |
|         |   parts:                               || existing part.            |
|         |     <alias-name>:                      || For example, to           |
|         |       type: alias                      || make it easier to         |
|         |       source: </path/to:existing-part> || reference it locally.     |
+---------+----------------------------------------+----------------------------+
| Enrich  | .. code-block:: yaml                   || Create an opinionated     |
|         |                                        || alternative to the        |
|         |   parts:                               || existing part by          |
|         |     <enriched-part-name>:              || initializing some of      |
|         |       type: enrich                     || its parameters, and       |
|         |       source: </path/to:existing-part> || overriding any of its     |
|         |       with:                            || properties. For           |
|         |         <param1>: <value1>             || example, to avoid         |
|         |         <param2>: <value2>             || passing the same set      |
|         |       offset: <OCCT-Location-obj>      || of parameters many times. |
+---------+----------------------------------------+----------------------------+


Other Part Types
----------------

Other methods to define parts are coming soon (e.g. `SDF <https://github.com/fogleman/sdf>`_).
Please, express your interest in support for other formats by filing a corresponding issue on GitHub
or sending an email to `support@partcad.org <mailto:support@partcad.org>`_.

Parameters
----------

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
(also referred to as ``MCFTT parameters`` using their first letters):

- ``material``

  Must point at an object of type ``material``.
  Some of them are defined in ``//pub/std/manufacturing/material``.
  When a request is made to a manufacturing API,
  a close enough material is selected from the materials provided by the
  manufacturer. The responsibility to select the right material is on the
  implementation of the manufacturing API (the ``provider`` object in PartCAD).

  **Not implemented yet. Use hardcoded values for now.**

- ``color``

  **Not implemented yet. Use color names for now.**

- ``finish``

  Optional. Can be omitted for no finish.

  **Not implemented yet.**

- ``texture``

  Optional. Can be omitted for no texture.

  **Not implemented yet.**

- ``tolerance``

  Optional. Can be omitted for a claim to perfect precision during manufacturing.

  **Not implemented yet.**

If the part has variable MCFTT parameters depending on the surface,
then either this part must be broken down into multiple parts,
or the values must be derived from CAD files/scripts (not implemented yet).
In the latter case the part will not be eligible for manufacturing features,
unless a specific manufacturing service provider recognizes (vendor,SKU) values
and have received corresponding manufacturing instructions out-of-band.

The MCFTT parameters are not required and have no impact on parts that have
``vendor`` and ``sku`` set and that are procured using providers of the type
``store``.

Manufacturing methods
---------------------

The ``manufacturing.method`` field says how a part is made:

+------------------+-----------------------------------------------------------+
| Method           | Meaning                                                   |
+==================+===========================================================+
| ``additive``     | Built up, e.g. 3D printed                                 |
+------------------+-----------------------------------------------------------+
| ``subtractive``  | Cut away from stock, e.g. machined                        |
+------------------+-----------------------------------------------------------+
| ``forming``      | Shaped without adding or removing material                |
+------------------+-----------------------------------------------------------+
| ``pcbBasic``     | A printed circuit board (**not implemented yet**)         |
+------------------+-----------------------------------------------------------+

These are ways of making a **part**, and apply to parts only. An assembly is put
together rather than made, and has a single method of its own -- see
:ref:`assembly-manufacturing` below.

A part that is bought rather than made carries ``vendor`` and ``sku`` instead of
a method.

.. _procurement:

Procurement
-----------

A part that can be bought off the shelf instead of being manufactured is
declared using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      # ...
      vendor: <(optional) the name of the vendor selling the part>
      sku: <(optional) the vendor's stock keeping unit (SKU) of the part>
      count_per_sku: <(optional) the number of parts in one SKU, 1 by default>

- ``vendor``

  Optional. The vendor that sells the part.

- ``sku``

  Optional. The vendor's `stock keeping unit
  <https://en.wikipedia.org/wiki/Stock_keeping_unit>`_ identifying what is
  ordered from that vendor.

  Both ``vendor`` and ``sku`` must be set for the part to be considered
  purchasable. If either is missing, the part has to be manufactured instead,
  which relies on the MCFTT parameters described above.

- ``count_per_sku``

  Optional. Defaults to ``1``. Must be a positive integer.

  The number of parts that come in a single SKU, for the parts that are sold in
  packs: a bag of 25 nuts is one SKU that yields 25 parts. Providers use it to
  translate the number of parts requested into the number of SKUs to order, and
  the number of SKUs a store has in stock into the number of parts it can
  supply.

These values are passed on to providers of the type ``store`` as
``request["vendor"]``, ``request["sku"]`` and ``request["count_per_sku"]``
(see :ref:`providers`).

Note that ``count_per_sku`` is a property of how the part is packaged for sale,
not of the CAD model. If the same part is sold by several vendors in different
pack sizes, declare one part per (vendor, SKU) pair, for example using
``alias``.

.. code-block:: yaml

  parts:
    nut_m4_0_7mm:
      type: step
      vendor: gobilda
      sku: "2803-0004-0002"
      count_per_sku: 25  # sold in bags of 25

.. _assemblies:

==========
Assemblies
==========

Declare assemblies
------------------

Assemblies are defined using the ``partcad.yaml`` file in the package folder. The syntax for defining assemblies is as follows:

.. code-block:: yaml

  assemblies:
    <assembly name>:
      type: <assy|step>  # Assembly YAML, or a STEP file with an assembly structure
      path: <(optional) the source file path>
      fileFrom: <(optional) "url" to download the source file instead of keeping it in the package>
      fileUrl: <(fileFrom=url only) the URL to download the source file from>
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>
      dependencies: # (optional) the list of filenames the caching logic checks for changes
        - <macros.j2>
        - <other.assy>
      offset: <(optional) OCCT Location object, e.g. "[[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]">

      # What this assembly contributes to every connection it takes part in.
      connect: # (optional) same as for parts
        hold: <(optional) name of an interface, or the list of them, to hold this assembly by>
        holdInstance: <(optional) instance of each interface listed in "hold", in the same order>
        holdForceMin: <(optional) least force to hold this assembly with, in N, default: 3>
        holdForceMax: <(optional) most force to hold this assembly with, in N, default: 7>
        holdForce: <(optional) sets both "holdForceMin" and "holdForceMax">

The ``assy`` type is used to define assemblies in `Assembly YAML` format, and
the ``step`` type reads the structure out of a STEP file (see :ref:`assembly_step`).
The ``path`` parameter specifies the source file path, and the ``parameters`` section allows for defining parameters that can be used within the assembly.
The source file does not have to be a part of the package: ``fileFrom`` and
``fileUrl`` pull it from a remote location on first use, exactly as they do for
:ref:`parts` (see :ref:`files`). This holds for every assembly type -- a vendor's
STEP assembly is declared with its URL and read from there.

.. _assembly-manufacturing:

**Manufacturing.** ``assy`` is the only manufacturing method an assembly has:
it is put together by following the instructions in its own Assembly YAML file,
rather than made the way a part is. Every assembly of type ``assy`` gets that
method with the type, so ``manufacturing`` never has to be spelled out:

.. code-block:: yaml

  assemblies:
    motor-mount:
      type: assy
      manufacturable: true
      # manufacturing: { method: assy } is implied by the type

Whether an assembly is *held to* that -- whether ``pc test`` checks that its
parts can be obtained and its connection instructions followed -- is what
``manufacturable`` says, exactly as for parts.

The optional ``offset`` parameter specifies the location of the assembly using an OCCT Location object.
See "Implementation Detail" for more information on the OCCT Location object.

Here is an example of an assembly definition:

.. code-block:: yaml

  assemblies:
    example_assembly:
      type: assy
      path: example.assy
      parameters:
        length:
          type: float
          default: 100.0
      offset: [[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]

In this example, an assembly named ``example_assembly`` is defined with a parameter ``length`` and an offset.

Assembly YAML
-------------

Here is an example of an assembly defined using `Assembly YAML`:

+---------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Configuration                                     | Result                                                                                                                  |
+===================================================+=========================================================================================================================+
| .. code-block:: yaml                              | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_assembly_assy/logo.svg?raw=true                |
|                                                   |   :width: 400                                                                                                           |
|   # partcad.yaml                                  |                                                                                                                         |
|   assemblies:                                     |                                                                                                                         |
|    logo:                                          |                                                                                                                         |
|      type: assy  # Assembly YAML                  |                                                                                                                         |
|                                                   |                                                                                                                         |
|   # logo.assy                                     |                                                                                                                         |
|   links:                                          |                                                                                                                         |
|   - part: /produce_part_cadquery_logo:bone        |                                                                                                                         |
|     location: [[0,0,0], [0,0,1], 0]               |                                                                                                                         |
|   - part: /produce_part_cadquery_logo:bone        |                                                                                                                         |
|     location: [[0,0,-2.5], [0,0,1], -90]          |                                                                                                                         |
|   - links:                                        |                                                                                                                         |
|     - part: /produce_part_cadquery_logo:head_half |                                                                                                                         |
|       name: head_half_1                           |                                                                                                                         |
|       location: [[0,0,2.5], [0,0,1], 0]           |                                                                                                                         |
|     - part: /produce_part_cadquery_logo:head_half |                                                                                                                         |
|       name: head_half_2                           |                                                                                                                         |
|       location: [[0,0,0], [0,0,1], -90]           |                                                                                                                         |
|     name: {{name}}_head                           |                                                                                                                         |
|     location: [[0,0,25], [1,0,0], 0]              |                                                                                                                         |
|   - part: /produce_part_step:bolt                 |                                                                                                                         |
|     location: [[0,0,7.5], [0,0,1], 0]             |                                                                                                                         |
+---------------------------------------------------+-------------------------------------------------------------------------------------------------------------------------+

The example above shows an assembly created using ``Assembly YAML``.
Other methods to define assemblies are coming soon (e.g. using ``CadQuery`` or ``build123d``).
The assembly file syntax is described in the ``Assembly YAML`` section of this documentation.

.. _assembly_step:

STEP
----

A STEP file that carries an assembly structure already says what an assembly
says: a tree of named components, each placed by a transform. The ``step`` type
reads it and uses it as the assembly itself, with no intermediate file:

.. code-block:: yaml

  assemblies:
    gearbox:
      type: step
      path: <(optional) the source file path, "{assembly name}.step" otherwise>
      precision: <(optional) decimal places each component's placement is rounded to, 5 by default>

``pc add assembly step <file>.step`` writes that declaration for an existing
file.

Every component of the STEP file becomes an ordinary PartCAD part, named
``<assembly name>/<component name>``. Those parts are inspected, rendered,
exported and referenced from other assemblies like any other part -- they are
simply declared by the STEP file rather than by ``partcad.yaml``:

.. code-block:: shell

  pc inspect -a :gearbox            # the assembly
  pc inspect :gearbox/output_shaft  # one component of it

A group inside the STEP file becomes a nested assembly, so the tree PartCAD
shows is the tree the CAD tool exported. Components that are the same geometry
in several places are recognized as one part placed several times, which is what
makes the bill of materials come out right.

Nothing is written into the package: the geometry PartCAD extracts for each
component is derived data and lives in PartCAD's own internal state directory.
The source file itself does not have to be in the package either -- with
``fileFrom``/``fileUrl`` (see :ref:`files`) a vendor's STEP assembly is declared
by its URL and downloaded the first time it is used:

.. code-block:: yaml

  assemblies:
    gearbox:
      type: step
      fileFrom: url
      fileUrl: https://example.com/vendor/catalog/gearbox.step

Compared to ``pc import assembly``
~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~

``pc import assembly`` reads the very same file with the very same reader, but
it is a one-shot conversion: it writes a STEP file per component and an
``Assembly YAML`` file into the package, and from then on the package owns them
and the original file is never consulted again.

Use ``type: step`` when the STEP file is to remain the source of truth: a
vendor's file, a file regenerated by another CAD tool, or a file pulled from a
URL. Every change to it is picked up on the next use, and nothing has to be
kept in sync by hand.

Use ``pc import assembly`` when the structure is to be taken over: the resulting
parts and ``.assy`` file are ordinary package content that can be renamed,
re-arranged, given interfaces and connections, or replaced part by part.

References
----------

It is also possible to declare assemblies by referencing other assemblies that are
already defined elsewhere. Unfortunately, ``enrich`` (documented in the `Parts` section) is not yet implemented for
assemblies.

+---------+--------------------------------------------+----------------------------+
| Method  | Configuration                              | Description                |
+=========+============================================+============================+
| Alias   | .. code-block:: yaml                       || Create a shallow          |
|         |                                            || clone of the              |
|         |   assemblies:                              || existing assembly.        |
|         |     <alias-name>:                          || For example, to           |
|         |       type: alias                          || make it easier to         |
|         |       source: </path/to:existing-assembly> || reference it locally.     |
+---------+--------------------------------------------+----------------------------+

Procurement
-----------

Not every assembly has to be assembled: some are sold assembled, as a kit or as
a pre-built module. Such an assembly is declared purchasable the same way a part
is (see :ref:`procurement`):

.. code-block:: yaml

  assemblies:
    <assembly name>:
      # ...
      vendor: <(optional) the name of the vendor selling the assembly>
      sku: <(optional) the vendor's stock keeping unit (SKU) of the assembly>
      count_per_sku: <(optional) the number of assemblies in one SKU, 1 by default>

``vendor``, ``sku`` and ``count_per_sku`` have the same meaning as they do for
parts, with the assembly itself being what is ordered.

.. code-block:: yaml

  assemblies:
    gearbox:
      type: assy
      vendor: gobilda
      sku: "3103-0001-0001"  # shipped assembled

An assembly that has both ``vendor`` and ``sku`` set is considered purchasable,
and is not required to declare how it is manufactured: ``pc test`` only checks
that a supplier carries it. An assembly without them is manufactured by producing
its parts and putting them together, which requires everything it is procured
from -- its parts, and the sub-assemblies that are sold assembled -- to be
obtainable by itself.

Declaring an assembly purchasable does not stop it from being modelled and
rendered as usual: the links between its parts still describe what is inside the
box.

This is also where ``pc supply find`` and ``pc supply quote`` stop looking
inside. An assembly is otherwise procured as the objects it is made of, and the
same question is asked about each sub-assembly in turn: one that is sold
assembled is ordered as a single item, and one that is not is broken down
further. Pass ``--recursive`` to order the parts even where the assembly holding
them could have been bought whole -- for example to compare the cost of building
it against the cost of buying it.

.. code-block:: shell

  # A chassis that uses the gearbox above: the gearbox is quoted as one unit,
  # and everything nobody sells assembled is quoted as the parts it is made of
  $ pc supply quote //robot:chassis

  # Quote every part of the chassis instead, the gearbox taken apart too
  $ pc supply quote --recursive //robot:chassis

An assembly embedded in the parent's own source file (the nested ``links:`` of
an Assembly YAML file) is not an object of any package, so there is no name to
order it by. Such an assembly is always procured as its contents, and declaring
a vendor for it has no effect.

.. _providers:

=========
Providers
=========

Providers are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  providers:
    <provider name>:
      type: <store|manufacturer|enrich>
      desc: <(optional) textual description>
      # ... type-specific options ...
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

``enrich`` providers are just references to other providers with some parameters
modified to specific values.

``store`` and ``manufacturer`` providers are implemented as Python scripts.
These scripts are invoked using the ``runpy`` module which allows to pass input
as values of global objects. The outputs are also extracted from the value of
global objects.

The input is passed as the dictionary ``request``.
The output is extracted from the dictionary ``output``

Store
-----

``store`` providers use the following input and output values:

- `request["parameters"]`: The configuration parameters of the provider.
- `request["api"]`: The API method called.

  - `request["api"] == "caps"`

    Get capabilities of this provider.
    Currently PartCAD does not use capabilities for ``store`` providers.

    - `output`: no output is expected

  - `request["api"] == "avail"`

    Check availability of the specific part.

    - `request["vendor"]`: the vendor of the part
    - `request["sku"]`: the SKU of the part
    - `request["count"]`: the requested quantity of the parts
    - `request["count_per_sku"]`: the known number of parts per SKU
    - `output["available"]`: boolean, whether it is available in this store

  - `request["api"] == "quote"`

    Get a quote for the specific cart of parts.
    Quote API is the core of the provider.
    It is expected to return the price of a cart.

    - `request["cart"]["parts"]`: the dictionary of parts
    - `request["cart"]["parts"][<id>]["vendor"]`: the vendor of the part
    - `request["cart"]["parts"][<id>]["sku"]`: the SKU of the part
    - `request["cart"]["parts"][<id>]["count"]`: the requested quantity of the parts
    - `request["cart"]["parts"][<id>]["count_per_sku"]`: the known number of parts per SKU
    - `output["price"]`: the total price of the cart
    - `output["cartId"]`: the id of the cart (to be used for the order later)

  - `request["api"] == "order"`

    Order the specific quote.
    Order API does not need to be implemented as there is no infrastructure
    for payments yet.

    - `request["cartId"]`: the id of the cart to be purchased

Manufacturer
------------

``manufacturer`` providers use the following input and output values:

- `request["parameters"]`: The configuration parameters of the provider.
- `request["api"]`: The API method called.

  - `request["api"] == "caps"`

    Get capabilities of this provider.

    - `output["materials"]`: the dictionary of supported materials

      .. code-block:: json

        {
            "//pub/std/manufacturing/material/plastic:pla": {
                "colors": [{"name": "red"}],
                "finishes": [{"name": "none"}]
            }
        }
    - `output["format"]`: the list of supported formats (e.g. `["step"]`)

  - `request["api"] == "quote"`

    Get a quote for the specific cart of parts.
    Quote API is the core of the provider.
    It is expected to return the price of a cart.

    - `request["cart"]["parts"]`: the dictionary of parts
    - `request["cart"]["parts"][<id>]["format"]`: the format of the binary (e.g. `"step"`)
    - `request["cart"]["parts"][<id>]["binary"]`: the geometry data
    - `output["price"]`: the total price of the cart
    - `output["cartId"]`: the id of the cart (to be used for the order later)

  - `request["api"] == "order"`

    Order the specific quote.
    Order API does not need to be implemented as there is no infrastructure
    for payments yet.

    - `request["cartId"]`: the id of the cart to be purchased

.. _repositories:

============
Repositories
============

A repository plugin serves the contents of a package: its objects, its child
packages and its metadata. It is what backs an ``external`` dependency (see
`External packages`_).

Repositories are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  repositories:
    <repository name>:
      type: <basic|enrich>
      desc: <(optional) textual description>
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

``enrich`` repositories are references to other repositories with some
parameters modified to specific values.

``basic`` repositories are implemented as Python scripts, invoked the same way
as provider scripts (via ``runpy``, with the input in the global ``request`` and
the output in the global ``output``). A repository script answers a single,
generic key/value request:

- `request["api"] == "get"`
- `request["key"]`: the key being requested
- `output["result"]`: the value stored under that key (or ``null`` if unknown)

The keys address every kind of data uniformly, so serving a new kind of object
or a new piece of metadata needs no new API:

- ``objects/<kind>`` -- all objects of a kind, as ``{name: config, ...}`` (kinds
  are ``sketch``, ``part``, ``assembly``, ``interface``, ``provider``,
  ``repository``)
- ``objects/<kind>/<name>`` -- a single object's config, fetched without listing
  the whole repository
- ``deps`` -- the names of the child packages
- ``meta`` -- package-level properties (``desc``, ``render``, ``manufacturable``,
  ...)
- ``files/<path>`` -- the base64-encoded content of a file an object references
  by ``path``. A plugin-backed package has no source tree, so a file-backed
  object's file is fetched from the plugin and materialized into the package's
  cache directory when the object is built.

For a hierarchy, a child package's requests are prefixed with its
``subfolder``: a child in ``motors`` asks for ``motors/objects/part``,
``motors/deps`` and so on, all served by the same script.

Responses are cached per key (in memory and on disk), so a repository that is
slow or remote is queried as little as possible. See
``examples/plugin_repository_basic``, ``examples/plugin_repository_full`` (an
HTTP-backed repository) and ``examples/plugin_repository_tree`` (a hierarchy).

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
      pythonRequirements: # (optional) what that script's sandbox needs
        - <requirement>
      pythonVersion: <(optional) the sandbox interpreter to run it on>
      extension: <(optional) the extension used when the file name is derived>
      prefix: <(optional) where the file goes, relative to the package>
      exclude: <(optional) kinds of object not to write this type for>
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

Built-in implementations
------------------------

The formats PartCAD ships are not special-cased anywhere: they are declared in
exactly the form above by two packages that live inside the ``partcad``
installation and that every context can reach, ``//builtin/export`` and
``//builtin/render``. They are the bottom layer of the configuration, so a
package that sets a single parameter keeps the built-in implementation for
everything else, and a package that sets ``path`` replaces it.

``//builtin/export`` implements ``step``, ``brep``, ``stl``, ``3mf``, ``obj``,
``gltf``, ``iges`` and ``threejs``. ``//builtin/render`` implements ``svg``,
``png``, ``jpeg`` and ``dxf``. Reading their ``partcad.yaml`` is the most direct
way to see what parameters each file type takes and what a package's own
implementation should look like.

``readme``, ``pdf`` and ``html`` are the outputs ``render:`` accepts that no
implementation writes: PartCAD assembles them itself out of what the package
declares and the images the other file types leave behind (see ``pc render`` in
:doc:`cli`).
