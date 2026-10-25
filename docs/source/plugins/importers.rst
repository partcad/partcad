.. _import-section:

#########
Importers
#########


``urdf``, ``sim-mujoco:mjcf`` and ``sim-gazebo:world`` are not object types
PartCAD hard-codes. Each is one entry of an ``import:`` section -- a declaration
saying which script reads that format, what its sandbox needs, and which object
kinds it may produce -- and a package writes one to teach PartCAD a format of its
own. That is not a hypothetical: ``urdf`` is the only one of the three PartCAD
ships, and the other two are entries of exactly this kind in the plugin package
for their engine.

.. code-block:: yaml

  import:
    demo:
      desc: The DemoCAD scene format
      path: read_demo.py           # the reader, in this package
      extension: demo              # the source file's extension
      kinds: [assembly, scene]     # what it may be declared as
      noun: model                  # what one is called in a log line
      pythonRequirements:
        - cadquery-ocp==7.9.3.1.1
      precision: 6                 # anything else is the reader's parameter
      dropped:
        joint: "joints (the object shows the bodies at their initial pose)"

An object then names it the way it names any object type. A reader in the same
package is named directly; one in another package is named by full path, exactly
as a :ref:`partType <part-types>` or a ``simulation:`` plugin is:

.. code-block:: yaml

  scenes:
    cell:
      type: sim-gazebo:world       # the reader in the imported package
      path: cell.world

The reader itself is handed the file and its parameters, and returns a tree of
placed shapes as plain data -- each node naming the *file* its geometry is read
from rather than carrying geometry. The part factory for that file's own format
reads it afterwards, so a mesh a scene references is never copied or rewritten.
Only the primitives a format defines (a box, a cylinder, a sphere) have no file
to name, and the reader writes those out itself. See
``wrappers/wrapper_import.py`` for the contract in full.

The file is a Jinja2 template like every other text file an assembly or a
scene is declared by, and is rendered before the reader sees it. A format whose
files are bytes (a DWG, say) says so, and its files are handed to the reader
exactly as they are on disk, never opened as text:

.. code-block:: yaml

  import:
    dwg:
      path: read_assembly.py
      extension: dwg
      binary: true

It is the declaration that decides, never the file's content: a binary file
whose bytes happen to decode is still not rendered, and a text format's file
that is not UTF-8 is reported as the broken template it is. Every object
PartCAD reads from a file is one of three kinds in this respect -- handed over
as it is, rendered as a template, or bytes -- and ``partcad.file_source`` is
where that is decided.

A reader runs where an output implementation of the same package would: in the
sandbox its own package describes (``pythonVersion``, ``pythonRequirements``,
``dockerImage``), never the one the package declaring the object does. It is
also handed ``request["cache_dir"]``, the directory its package keeps what it
downloads on first use in -- a converter pip cannot install, for one -- exactly
as a ``partType`` and an output implementation are.

Two fields are worth dwelling on. ``kinds:`` is a claim the core holds the
declaration to: a format that describes one robot is an assembly and declaring
it under ``scenes:`` is an error, while a format used for both -- MJCF is the
one that routinely is -- says both and lets the section decide. ``dropped:``
words what the reader counted: every one of these formats describes something a
static tree cannot hold, and the division of labour is that the *reader* counts
what it had to drop and the *declaration* says what to call it.

The section shares its name with what ``dependencies:`` used to be called, and
that spelling is reported rather than silently migrated now: a package whose
``import:`` entries carry a ``type:`` of ``git``/``tar``/``local``/``external``,
or any of the transport-only keys (``url``, ``relPath``, ``revision``, ...), is
told to rename the section, and those entries are dropped instead of being
fetched as packages. Nothing is migrated for it.

How loudly depends on whose package it is. In the package you are standing in it
is an error and the package is broken -- the command exits non-zero and nothing
loads out of it, because that is the file you can fix. In an imported package it
is a warning naming the package, the entry and the fix: such a package is very
often somebody else's, several levels below anything you wrote, and one of them
anywhere in an index must not fail every command that merely walks past it. That
package goes on providing everything else it declares; what is lost is exactly
what the section named.

PartCAD ships **one** of these, in ``//builtin/import``: ``urdf``, which stays
there because a URDF describes a robot rather than any one engine's world, and
ROS, MuJoCo, PyBullet and Isaac all read it. ``mjcf`` and ``world`` belong to
`partcad-sim-mujoco <https://github.com/partcad/partcad-sim-mujoco>`_ and
`partcad-sim-gazebo <https://github.com/partcad/partcad-sim-gazebo>`_
respectively, beside the exporter and the simulator that share their knowledge
of the format: reading a format and writing it are one piece of knowledge, and
this is what lets the pair travel together and be versioned together.

Each of those packages declares the reader, the writer, the simulator and the
``open:`` entry for its format, and the wheel carries none of them. So
``type: sim-gazebo:world`` and ``type: sim-mujoco:mjcf`` are the spellings that
resolve, in a package that imports the plugin; a bare ``type: world`` resolves to
nothing and says which package to name.
