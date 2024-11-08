Use Cases
#########

PartCAD provides a public repository of parts and assemblies, and various tools
and frameworks to operate with those parts and assemblies.
Depending on particular goals, different ways of interacting with PartCAD tools
and data may be desired. Below is a list of some common use cases.

=======================
Browse available models
=======================

Online
------

The web UI to browse the public PartCAD repository is available at
`partcad.org <https://partcad.org/>`_.

Visual Studio Code extension
----------------------------

The PartCAD extension is
`available <https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad>`_
in VS Code extension marketplace.

Command line tools
------------------

Whether you consider publishing new CAD models or consuming already existing ones,
it makes sense to browse what's already available.

The PartCAD's integration into WebAssembly is not yet completed and, thus, there
is currently no public website where you can browse the public PartCAD
repository.

The command line tools are the easiest way to browse parts:

  .. code-block:: shell

    # Initialize a new PartCAD package in the current folder
    pc init

    # List all available packages
    pc list

    # List all sketches in all available packages
    pc list-sketches -r

    # List all interfaces in all available packages
    pc list-interfaces -r

    # List all known matings of interfaces in all available packages
    pc list-mates -r

    # List all parts in all available packages
    pc list-parts -r

    # List all assemblies in all available packages
    pc list-assemblies -r

    # Try initializing the model, print some basic info without displaying it
    pc info /pub/std/metric/cqwarehouse:fastener/hexhead-din931

    # Display the model in OCP CAD Viewer
    pc inspect /pub/std/metric/cqwarehouse:fastener/hexhead-din931

    # Display the parametrized model
    pc inspect \
        -p length=30 \
        -p size=M4-0.7 \
        /pub/std/metric/cqwarehouse:fastener/hexhead-din931

The last command displays the chosen part in
``OCP CAD Viewer`` view in Visual Studio Code.
There is currently no support for ``cq-server``.
Please, let `support@partcad.org <mailto:support@partcad.org>`_ know if there is
any other tool we should support.

=============
Export models
=============

Individual parts, assemblies and scenes can be rendered and exported into the
following formats:

- Vector images

  - SVG

- Raster images

  - PNG

- 3D models

  - `STEP <https://en.wikipedia.org/wiki/ISO_10303>`_
  - `STL <https://en.wikipedia.org/wiki/STL_(file_format)>`_
  - `3MF <https://en.wikipedia.org/wiki/3D_Manufacturing_Format>`_
  - `ThreeJS <https://en.wikipedia.org/wiki/Three.js>`_
  - `OBJ <https://en.wikipedia.org/wiki/Wavefront_.obj_file>`_

Expect more output formats to be added to the list of supported export formats
in the future.

  .. code-block:: shell

    pc render -t stl <part path>
    pc render -t step -a <assembly path>

==============
Consume models
==============

CAD Design GUIs
---------------

If you want to use models from the public PartCAD repository in a CAD Design GUI
(like FreeCAD or its paid alternatives), the best way to do it at the moment
(before PartCAD plugins for these apps are available) is to export the models to
STEP or 3MF files and, then, import them into the CAD Design GUI of your choice.

  .. code-block:: shell

    # Some "export to a file" examples:
    pc render -t stl <part> [<package>]
    pc render -t step -a <assembly> [<package>]

Python: CadQuery
----------------

Here are some examples of how to fetch PartCAD models from within a ``CadQuery``
script:

  .. code-block:: python

    # part.py
    import cadquery as cq
    import partcad as pc
    part = pc.get_part_cadquery(
        "/pub/std/metric/cqwarehouse:fastener/hexhead-din931",
    )
    ...
    show_object(part)

  .. code-block:: python

    # assembly.py
    import cadquery as cq
    import partcad as pc
    assembly = pc.get_assembly_cadquery(
        "/pub/furniture/workspace/basic:imperial-desk-1",
    )
    ...
    show_object(assembly)

Python: build123d
-----------------

Here are some examples of how to fetch PartCAD models from within a
``build123d`` script:

  .. code-block:: python

    # part.py
    import build123d as b3d
    import partcad as pc
    part = pc.get_part_build123d(
        "/pub/std/metric/cqwarehouse:hexhead-din931",
    )
    ...
    show_object(part)

  .. code-block:: python

    # assembly.py
    import build123d as b3d
    import partcad as pc
    assembly = pc.get_assembly_build123d(
        "/pub/furniture/workspace/basic:imperial-desk-1",
    )
    ...
    show_object(assembly)

Python
------


  .. code-block:: python

    # part.py
    import partcad as pc

    part = pc.get_part(
        "/pub/std/metric/cqwarehouse:fastener/hexhead-din931",
    )
    part.show()

  .. code-block:: python

    # assembly.py
    import partcad as pc

    assembly = pc.get_assembly(
        "/pub/furniture/workspace/basic:imperial-desk-1",
    )
    assembly.show()


shell
-----

  .. code-block:: shell

    # custom.sh
    for part in $PART_LIST; do
      pc render -t png $part
    done

  .. code-block:: shell

    # custom.sh
    for assembly in $ASSEMBLY_LIST; do
      pc render -t png -a $assembly
    done

==============
Produce models
==============

Part: Files
-----------

One way to define parts in PartCAD is by providing a file in any of the currently
supported formats: STEP, STL, 3MF. There is no intention to limit the list of
file formats supported. Contribute support of your favorite file format
(ideally, implicitly, by adding the corresponding support to build123d).

   .. code-block:: yaml

    # partcad.yaml
    parts:
        part1:
            type: step # part1.step is used
        part2:
            type: stl # part2.stl is used
        part3:
            type: 3mf # part3.3mf is used

Part: CAD scripts
-----------------

Another way to define parts is by using CAD scripting technologies such
as OpenSCAD. This is the only CAD scripting language supported at the moment.
The fundamental difference from CAD files listed above is the availability of
parameters. However OpenSCAD parameters are not yet supported.

  .. code-block:: yaml

    # partcad.yaml
    parts:
        part1:
            type: scad # part1.scad is used


Part: Python scripts
--------------------

The most powerful way to define parts is by using modeling frameworks such as
CadQuery and build123d. PartCAD uses CQGI to load models
(in other words: intercepts `show_object()` calls).

  .. code-block:: yaml

    # partcad.yaml
    parts:
        part1:
            type: cadquery # part1.py is used
        optional-path/part2:
            type: build123d # optional-path/part2.py is used

Part: AI-generated
------------------

PartCAD can generate CadQuery and OpenSCAD scripts using GenAI models from
Google and OpenAI.
This is the fastest way to bootstrap most designs.
Empty the generated file and iteratively improve the prompts until the desired
script functionality is achieved.
Alternatively, drop the AI parameters and continue improving the script manually.

  .. code-block:: yaml

    # partcad.yaml
    parts:
        part1:
            type: ai-cadquery # part1.py is created
            desc: A cube
            provider: google
        part2:
            type: ai-openscad # part2.scad is created
            desc: A flat screen TV
            provider: openai
            images:
              - product_photo.png

The following configuration is required:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    googleApiKey: <...>
    openaiApiKey: <...>

Assembly
--------

  .. code-block:: yaml

    # partcad.yaml
    assemblies:
        logo:
            type: assy

  .. code-block:: yaml

    # logo.assy
    links:
      - part: /produce_part_cadquery_logo:bone
        location: [[0,0,0], [0,0,1], 0]
      - part: /produce_part_cadquery_logo:bone
        location: [[0,0,-2.5], [0,0,1], -90]
      - links:
          - part: /produce_part_cadquery_logo:head_half
            location: [[0,0,2.5], [0,0,1], 0]
          - part: /produce_part_cadquery_logo:head_half
            location: [[0,0,0], [0,0,1], -90]
        location: [[0,0,25], [1,0,0], 0]
      - part: /produce_part_step:bolt
        package:
        location: [[0,0,7.5], [0,0,1], 0]

================
Publish packages
================

It's very simple to publish your package to the public PartCAD repository.
First, publish your package as a repo on GitHub.
Then create a pull request in
`the public PartCAD repo <https://github.com/openvmp/partcad-index>`_
to add a reference to your package.
