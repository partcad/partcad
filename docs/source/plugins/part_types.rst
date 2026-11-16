##########
Part types
##########

A **part type plugin** teaches PartCAD how to build a part. The types PartCAD
implements itself -- ``build123d``, ``cadquery``, ``openscad``, ``step``,
``stl``, and the rest of :ref:`the list <part-types>` -- are what a part's
``type:`` normally names. A ``partTypes:`` section declares one more, belonging
to the package that writes it, and parts then name that instead.

It is worth doing when **a family of parts is produced the same way every time**
and the difference between them is a handful of parameters rather than a script
each: parts generated from a table, fetched from a catalogue, or built by a
modelling helper the package already has. Twenty bolts become twenty parameter
sets and one script, not twenty scripts.

What a part type is for
=======================

- **A parametric family.** One script, a ``parameters:`` block per part. The
  script is the only place the geometry is written down, so a fix to it fixes
  every part of the family at once.
- **A catalogue.** A type that reads a vendor's table or API and returns the
  shape for a given part number, so the package's parts are the part numbers.
- **A house modelling convention** -- a profile system, a sheet-metal
  enclosure, a connector family -- published once as a package other packages
  import.
- **A kernel or a helper PartCAD does not know about.** The script runs in its
  own sandbox and can import whatever it needs -- or, for a program ``pip`` cannot
  install, in a container image that carries it (see `Running in a container`_).

Using one
=========

A ``type:`` beginning with ``:`` names a part type of the part's own package and
is expanded to ``<package path>:<name>`` when the package loads. Write the
package path out to use another package's:

.. code-block:: yaml

  dependencies:
    profiles:
      type: git
      url: https://example.com/partcad-profiles

  parts:
    upright:
      type: profiles:extrusion     # a part type from the imported package
      parameters:
        profile: 2020
        length: 300

A part built this way is an ordinary part in every other respect: it renders,
exports, tests, goes into assemblies and into a bill of materials. A part type
is listed like any other object but **is never a shape in its own right** -- it
is how parts are made, not one of them.

Writing one
===========

.. code-block:: yaml

  partTypes:
    box:
      kind: wrapper              # the default, and currently the only kind
      path: box_wrapper.py       # "<name>.py" if left out
      pythonRequirements:        # what this script's sandbox needs
        - build123d==0.9.1

  parts:
    demo:
      type: ":box"
      parameters:
        size:
          type: float
          default: 12

The script is run in the sandbox once per part, with the part's ``request`` in
its globals -- the resolved ``parameters`` among them -- and leaves the geometry
in a global ``output``:

.. code-block:: python

  if __name__ == "__partcad_part__":
      from build123d import Box

      size = float(request["parameters"].get("size", 10))
      output = {"shape": Box(size, size, size).wrapped}

Because the script runs in a sandbox it may import OCP, build123d or CadQuery.
This is the same mechanism as an :doc:`output implementation </plugins/output>`,
pointed at building a shape rather than at writing a file.

Two things to get right:

``CACHE_VERSION``
  A part built by a part type is cached like any other, keyed on the version the
  script reports as well as on the part's own configuration -- a module-level
  ``CACHE_VERSION = <int>``, read **without running the script**. Raise it
  whenever a change to the script changes the parts it builds; an edit that does
  not -- a comment, a refactoring -- then costs nobody a rebuild. Forgetting to
  raise it is the one failure mode here, and it shows up as a stale shape.

``pythonRequirements`` belongs to the plugin
  It is read from the package that ships the script and from nowhere else, so a
  part type's dependencies never reach the package using it.

.. _part-type-container:

Running in a container
======================

A part type -- or a sketch type, which declares it the same way (see
:doc:`/plugins/sketch_types`) -- whose script drives a **native program** -- a CSG kernel written in
Rust, a converter shipped as a binary, a whole CAD application -- needs more than
``pip`` can install. It can download the program into ``request["cache_dir"]`` on
first use, or it can declare the image that carries it, and have its script run
there:

.. code-block:: yaml

  partTypes:
    cube:
      path: cube.py
      container: ghcr.io/example/csg-tools:1.2.0      # pinned: the cache is keyed on it

    # the long form, same meaning
    sphere:
      path: sphere.py
      container:
        image: ghcr.io/example/csg-tools:1.2.0
        name: csg            # what the container is for: partcad-plugin-csg-...
        command: python      # the name in the image's allowlist it runs with (the default)

The script runs in that image **as it is**: no sandbox environment is built in
it, nothing from ``pythonRequirements`` is installed into it, and ``dockerImage``
is not read for that type -- both describe a Python sandbox the type does not run
in. The container is started the way PartCAD starts every container (see
``tools/containers/README.md``), shared by every part built with that image, and
kept for as long as PartCAD runs. A machine with no container runtime cannot build
such a part, and says so, naming the image; there is no fallback to a sandbox.

What the image needs
--------------------

- **A ``python3``**, which PartCAD runs its own service on, and the allowlist entry
  the type runs with (``python`` unless ``command:`` names another) --
  ``PC_CONTAINER_ALLOWED_COMMANDS``.
- **OCP**, importable by that interpreter. What runs in the container is
  PartCAD's own wrapper, sent with every command rather than baked into the image,
  and it hands the shape back as an OCP shape; a script cannot do without it
  either, since a shape is what it builds. An image without it fails every part
  with a message saying so, before the script runs.
- **The program**, anywhere the script can run it from: the script runs as an
  ordinary process in the container, and the allowlist only says what PartCAD
  may start, not what that may start in turn.

The way to get the first two is to build ``FROM`` PartCAD's own base image and
install build123d at the version PartCAD pins (``sandbox_versions.BUILD123D``),
which brings the OCP build PartCAD's wrappers use:

.. code-block:: dockerfile

  ARG BASE=ghcr.io/partcad/partcad-container-python:py3.12-amd64
  FROM ${BASE}

  USER root
  RUN pip install --no-cache-dir build123d==0.11.1
  COPY --chmod=0755 csg /usr/local/bin/csg
  USER pc

  LABEL partcad.image="1"

and the script, which writes nothing PartCAD has to know about:

.. code-block:: python

  import os
  import subprocess
  import tempfile

  CACHE_VERSION = 1

  if __name__ == "__partcad_part__":
      from build123d import import_stl

      size = float(request["parameters"].get("size", 10))
      with tempfile.TemporaryDirectory() as scratch:
          stl = os.path.join(scratch, "cube.stl")
          subprocess.run(["csg", "cube", str(size), "-o", stl], check=True)
          output = {"shape": import_stl(stl).wrapped}

A closed shell, which is what a mesh comes back as, is stated as the solid it
bounds before it is handed over, so the script need not do that itself.

Files
-----

What the script reads reaches it whichever way files reach the container
(``useDockerRemote``, ``PC_USE_DOCKER_REMOTE``):

- in **mount** mode, the default, the home and temporary directories, the context
  root and PartCAD's installation are mounted at the paths they have here, so
  ``request["path"]`` and ``request["cache_dir"]`` are the paths they would be in
  a sandbox;
- in **upload** mode nothing is mounted: the type's package, the part's file and
  the cache directory are sent (by content, so once per container), the paths in
  the request are those they were unpacked to, and what the script wrote into
  ``request["cache_dir"]`` comes back when it ends. So a script finds every file by
  the request and never by a path of its own, and keeps what it has to keep in the
  cache directory, the only one it writes into that comes back.

Caching
-------

A part built in a container is keyed on the image as it was declared and on the
name it runs with -- in place of the interpreter and requirements a sandboxed
part is keyed on -- besides its own configuration and the script's
``CACHE_VERSION``. So a new image is a new tag: one rebuilt under the same tag is
the same key, and the shapes the old one built are what is served. Pin it.

An example
==========

``examples/produce_part_wrapper`` is the whole thing in two files. The package
declares one part type and one part built with it:

.. code-block:: yaml

  partTypes:
    box:
      kind: wrapper
      path: box_wrapper.py

  parts:
    demo:
      type: ":box"
      desc: A box built by the 'box' wrapper partType.
      parameters:
        size:
          type: float
          default: 12

``box_wrapper.py`` is the script above. From that directory:


.. code-block:: shell

  pc list parts          # 'demo' is listed; 'box' is not a part
  pc info :demo          # the resolved parameters, the bounding box, the volume
  pc render :demo        # a picture of it, like any other part
  pc ide view :demo      # or in the Digital Thread

.. image:: /images/plugin-part-type.png
  :width: 100%
  :align: center
  :alt: The part built by the box partType, shown in the Digital Thread

``box`` is absent from ``pc list parts``, because it is a ``partType`` and not a
part -- PartCAD counts the two as different kinds of object (``partType`` is one
of those in ``Project.OBJECT_KINDS``), and only one of them is a shape.

A sketch is built by a package-defined type the same way, through a
``sketchTypes:`` section: see :doc:`/plugins/sketch_types`.
