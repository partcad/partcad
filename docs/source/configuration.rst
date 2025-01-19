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

  name: <(optional) for advanced users, the assumed package path for standalone development>
  desc: <(optional) description>
  private: <(optional) boolean flag to mark the package as private>
  url: <(optional) package or maintainer's url>
  poc: <(optional) point of contact, maintainer's email>
  partcad: <(optional) required PartCAD version spec string>
  pythonVersion: <(optional) python version for sandboxing if applicable>
  pythonRequirements: <(python scripts only) the list of dependencies to install>

  dependencies:
      <dependency-name>:
          desc: <(optional) textual description>
          type: <(optional) git|tar|local, can be guessed by path or url>
          path: <(local only) relative path to the package>
          url: <(git|tar only) URL of the package>
          relPath: <(git|tar only) relative path within the repository>
          revision: <(git only) the exact revision to import>
          includePaths: <(optional) Jinja2 include path>

  parts:
      <part declarations, see below>

  assemblies:
      <assembly declarations, see below>

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

When the source file is not present in the package source repository
but needs to be pulled from a remote location, the following options can be used:

.. code-block:: yaml

  fileFrom: url
  fileUrl: <url to pull the file from>
  # fileCompressed: <(optional) whether the file needs to be decompressed before use>
  # fileMd5Sum: <(optional) the MD5 checksum of the file>
  # fileSha1Sum: <(optional) the SHA1 checksum of the file>
  # fileSha2Sum: <(optional) the SHA2 checksum of the file>

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

.. _sketches:

Other
-----

There are other optional fields that are common to all objects:

- ``desc``: <text>

  Description of the object.

- ``offset``: <OCCT Location object>

  Defines the offset to apply to the CAD model when this object is used.

- ``cache``: <bool> (default: `True`)

  The value `false` indicates the intent to exclude this object from any cacheing behavior.
  It may be due to size or time considerations, or due to known issues with dependency tracking.
  It does not override any global caching settings.

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
      type: <openscad|cadquery|build123d|ai-openscad|ai-cadquery|ai-build123d|step|brep|stl|3mf|extrude|sweep>
      desc: <(optional) textual description, also used by AI>
      path: <(optional) the source file path, "{part name}.{ext}" otherwise>
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

Depending on the type of the part, the configuration may have different options.

See :ref:`location` for more information on the OCCT Location object.

CAD Scripts
-----------

Define parts with CodeCAD scripts using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <openscad|cadquery|build123d>
      cwd: <alternative current working directory>
      showObject: <(optional) the name of the object to show using "show_object(...)">
      patch:
        # ...regexp substitutions to apply...
        "pattern": "repl"
      pythonRequirements: <(python scripts only) the list of dependencies to install>
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

AI Generated CAD Scripts
------------------------

Generate OpenSCAD, CadQuery or build123d scripts with Generative AI using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      desc: <(optional) The detailed description to be used in the model generation prompt>
      requirements: <(optional) The list of requirements to be used in the model generation prompt>
      type: <ai-openscad|ai-cadquery|ai-build123d>
      provider: <google|openai|ollama, the model provider to use>
      model: <(optional) the model to use>
      tokens: <(optional) the limit of token context>
      temperature: <(optional) the temperature LLM parameter>
      top_p: <(optional) the top_p LLM parameter>
      top_k: <(optional, openai|ollama) the top_k LLM parameter>

Place the detailed description of the part in the ``desc`` field.
Provide as much information as possible through the :ref:`requirements` field,
using ``INCLUDE(<filename>)`` or ``DOWNLOAD(<url>)`` to add supported
file formats to the prompt either from a file in the package folder or from a URL.

The following models are recommended for use:

+----------+----------------------------+
| Provider | Model                      |
+==========+============================+
| google   | - gemini-1.5-pro (default) |
|          | - gemini-1.5-flash         |
+----------+----------------------------+
| openai   | - gpt-4o (default)         |
|          | - gpt-4o-mini              |
+----------+----------------------------+
| ollama   | - llama-3.1:8b             |
|          | - llama-3.1:70b (default)  |
|          | - llama-3.1:405b           |
+----------+----------------------------+

+---------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Example                   | Result                                                                                                                  |
+===========================+=========================================================================================================================+
| .. code-block:: yaml      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_ai_cadquery/cube.svg?raw=true             |
|                           |   :width: 128                                                                                                           |
|   parts:                  |                                                                                                                         |
|     cube:                 |                                                                                                                         |
|       type: ai-cadquery   |                                                                                                                         |
|       provider: google    |                                                                                                                         |
|       desc: A cube        |                                                                                                                         |
+---------------------------+-------------------------------------------------------------------------------------------------------------------------+

CAD Files
---------

Define parts with CAD files using the following syntax:

.. code-block:: yaml

  parts:
    <part name>:
      type: <step|brep|stl|3mf>
      binary: <(stl only) use the binary format>

+--------------------------------------------------------------------------------------+---------------------------+-------------------------------------------------------------------------------------------------------------------------+
| Example                                                                              | Configuration             | Result                                                                                                                  |
+======================================================================================+===========================+=========================================================================================================================+
|| CAD file                                                                            | .. code-block:: yaml      | .. image:: https://github.com/partcad/partcad/blob/main/examples/produce_part_step/bolt.svg?raw=true                    |
|| (`STEP <https://en.wikipedia.org/wiki/ISO_10303>`_ in ``screw.step``,               |                           |   :width: 128                                                                                                           |
|| `STL <https://en.wikipedia.org/wiki/STL_(file_format)>`_ in ``screw.stl``,          |   parts:                  |                                                                                                                         |
|| or `3MF <https://en.wikipedia.org/wiki/3D_Manufacturing_Format>`_ in ``screw.3mf``) |     screw:                |                                                                                                                         |
|                                                                                      |       type: step          |                                                                                                                         |
|                                                                                      |       # type: stl         |                                                                                                                         |
|                                                                                      |       # type: 3mf         |                                                                                                                         |
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
  Some of them are defined in ``/pub/std/manufacturing/material``.
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
      type: assy  # Assembly YAML
      path: <(optional) the source file path>
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>
      offset: <(optional) OCCT Location object, e.g. "[[x_off,y_off,z_off], [x_rot,y_rot,z_rot], rot_angle]">

The ``assy`` type is used to define assemblies in `Assembly YAML` format.
The ``path`` parameter specifies the source file path, and the ``parameters`` section allows for defining parameters that can be used within the assembly.
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
            "/pub/std/manufacturing/material/plastic:pla": {
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
