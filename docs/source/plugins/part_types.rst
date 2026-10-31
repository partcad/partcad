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
  own sandbox and can import whatever it needs.

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
of the ten in ``Project.OBJECT_KINDS``), and only one of them is a shape.
