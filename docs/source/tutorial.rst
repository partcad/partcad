Tutorial
########

============
Command Line
============

Create a package
----------------

First, the current directory needs to be initialized as a PartCAD package.

  .. code-block:: shell

    # Initialize the new PartCAD package in the current folder
    pc init

If there is no ``-p`` flag passed to ``pc init``
then the dependency on the public PartCAD repository is added automatically.

Alternatively, manually create ``partcad.yaml`` with the following content:

  .. code-block:: yaml

    # partcad.yaml
    dependencies:
      # Public PartCAD repository (reference it explicitly if required)
      pub:
        type: git
        url: https://github.com/partcad/partcad-index.git

Now launch ``pc list`` to see the list of packages currently available in
the public PartCAD repository.

  .. code-block:: shell

    # Recursively iterate over all dependencies of the current package
    pc list

Manage dependencies
-------------------

PartCAD has to be provided with a configuration file which may declare parts and
assemblies, but also declares all repositories that PartCAD is allowed to query.

PartCAD has no implicit dependencies built-in,
so a dependency on the public PartCAD repository needs to be added
if PartCAD is supposed to query it.

In the newly created package, comment out the "pub" dependency (prepend ``#``)
and see how the output of ``pc list`` changes.

Add a part
----------

Let's add a part defined using an OpenSCAD script.

First, create the OpenSCAD script which defines a cube of size 10mm.

  .. code-block:: shell

    # Create "test.scad"
    echo "translate (v= [0,0,0])  cube (size = 10);" > test.scad

Now let's add a declaration of this part to ``partcad.yaml``.

  .. code-block:: shell

    pc add part scad test.scad

Import an existing part
-----------------------

The `pc import part` command allows you to import an existing part into a PartCAD project.
You can also specify a target format to convert the part upon import.

Basic import:

.. code-block:: shell

    # Import a STEP file
    pc import part step my_part.step

Import and convert to STL:

.. code-block:: shell

    # Import a STEP file and convert it to STL format
    pc import part step my_part.step -t stl

Provide an optional description:

.. code-block:: shell

    pc import part stl my_model.stl --desc "3D model of a mechanical part"

Example log output:

.. code-block:: text

    pc import part step my_part.step -t stl
    INFO: Importing part: my_part.step (step)
    INFO: Performing ad-hoc conversion: step → stl
    INFO: Ad-hoc conversion successful: my_part.stl
    INFO: Successfully imported part: my_part

.. note::
    - The imported part is added to the project directory.
    - If a target format is specified, the part is converted automatically.


Inspect the part
----------------

Once a part is created, it can be inspected in ``OCP CAD Viewer``.

  .. code-block:: shell

    pc inspect :test

Export the part
---------------

Now the part can be exported:

  .. code-block:: shell

    pc export -t stl :test

==================
Convert a CAD File
==================

The `pc adhoc convert` command allows you to quickly convert a CAD file from one format to another without requiring a full project setup or configuration.

Supported formats:
------------------
- **Input:** STL, STEP, BREP, 3MF, SCAD, CadQuery, Build123d
- **Output:** STL, STEP, BREP, 3MF, ThreeJS, OBJ, GLTF, IGES

Examples:
---------

.. code-block:: shell

    # Type inference from extensions
    pc adhoc convert part.stl model.step  # STL to STEP

    # Explicit type specification
    pc adhoc convert input output.stl --input scad --output stl

    # Default output filename
    pc adhoc convert input.stl --output step  # Creates input.step

.. note::
    If the conversion fails, the command will display an error message and exit with a non-zero status code.

===================================
Convert a Part
===================================

The `pc convert` command allows you to convert parts, assemblies, or sketches to a different format.
It supports optional output directory specification and a dry-run mode for simulation.

Usage:
---------

To convert a part from STL to STEP format:

.. code-block:: shell

    # Convert the part "cube" to STEP format
    pc convert cube -t step

To specify an output directory for the converted files:

.. code-block:: shell

    # Convert the part "cube" to STEP format and save it in the specified directory
    pc convert cube -t step -O ./output

Simulate conversion without modifying files
-------------------------------------------

The `--dry-run` option allows you to simulate the conversion process without making any changes.
This is useful for verifying which files would be affected before performing the actual conversion.

.. code-block:: shell

    # Simulate converting "cube" to STEP format without modifying anything
    pc convert cube -t step --dry-run

    # Example output:
    # INFO: Starting conversion: 'cube' → 'step', dry_run=True
    # INFO: Resolving package '', part 'cube'
    # INFO: Using project '', located at '/workspaces/partcad/examples'
    # INFO: Converting 'cube' (stl → step) → '/workspaces/partcad/examples/cube.step'
    # INFO: [Dry Run] No changes made for 'cube'.

This option ensures that no files are created or modified, and only logs the expected conversion actions.

Supported formats:
------------------
- STEP
- BREP
- STL
- 3MF
- Three.js (JSON)
- OBJ
- glTF (JSON)
- IGES

.. note::
    - The object must exist in the `partcad.yaml` file and be defined as a part.
    - If the target format is not supported by the object, an error will be displayed, and the conversion will be aborted.
    - The `--dry-run` option only simulates the conversion process without making actual changes.
    - The converted file will be saved in the same directory as the original unless an output directory is specified.

Reset partcad
---------------------

PartCAD maintains an internal state to keep track of dependencies of a project. This state can be reset using the command below.

  .. code-block:: shell

    pc system reset

=================
VS Code Extension
=================

Start new workspace
-------------------

Open Visual Studio Code and create a new empty workspace.

Activate Python
---------------

If necessary, install the Python extension.
Activate a Python environment (3.10 or above).

Install the extension
---------------------

Install the
`PartCAD <https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad>`_
extension from the VS Code marketplace.

Install PartCAD
---------------

Switch to the PartCAD workbench
(look for the PartCAD logo at the left edge of the screen).
There is the PartCAD Explorer view on the left.
Click ``Install PartCAD`` in the Explorer view if this button is shown
to install PartCAD in the activated Python environment.

Create a package
----------------

Once PartCAD is initialized, it won't detect any PartCAD package in the empty
workspace.
Click ``Initialize Package`` to create ``partcad.yaml``.

Browse
------

Browse the imported packages in the Explorer view. Click on the parts and
assemblies to see them in the ``OCP CAD Viewer`` view that will appear on the
right.

For example, navigate to ``//pub/std/metric/cqwarehouse`` and click on some part
(e.g. ``fastener/hexhead-din931``).
The PartCAD Inspector view displays the part parameters.
The parameter values can be changed and the part gets redrawn on ``Update``.

Create a part
-------------

Click ``Add a CAD script`` in the Explorer view toolbar.
Select ``build123d`` from the dropdown list.
Then select ``Example 3: Bead`` as the template to use.
An editor view with the newly created script will be shown.

Inspect the part
----------------

When you edit Python or OpenSCAD files that are used in the current
PartCAD package, saving the file makes it displayed automatically.
Press ``Save`` (Ctrl-S or Cmd-S) to save the script and trigger an automatic
inspection of the part. The ``OCP CAD Viewer`` view will appear on the right.

Import parts part
-----------------

In case you want to use existing PartCAD parts in the design of your part,
then follow the following steps.

First, select the part you want to use in the PartCAD Explorer view.
Then, add the following to the ``build123d`` script created during the previous
steps of this tutorial:

  .. code-block:: python

    import partcad as pc

    other_part = pc.get_

Please, note, that after "``pc.get_"`` a code completion suggestion appears.
Use the suggested code completion option to insert the code that adds
the selected part to this ``build123d`` script.

Here is an example of how to use the newly added solid:

  .. code-block:: python

    ...
    # After "with BuildPart"
    art = Compound([art, other_part])
    # Before "show_object"
    ...

Import an Assembly
------------------

The ``pc import assembly`` command allows you to import an assembly from a STEP file.
This command automatically parses the STEP file, extracts individual parts,
and creates an assembly YAML file that records each part along with its transformation data.

Usage
^^^^^

.. code-block:: shell

   # Import an assembly from a STEP file with an optional description
   pc import assembly step my_assembly.step --desc "Optional assembly description"

Functionality
^^^^^^^^^^^^^

- **File Parsing:**
  The command first attempts to parse the STEP file using an XDE-based approach.
  If no parts are found via XDE, it falls back to a classic STEP parsing method.

- **Duplicate Filtering:**
  Unique parts are identified by comparing the geometric data and applied transformations.
  Duplicate entries are discarded based on a composite key of shape identifier and transformation.

- **Part Extraction:**
  Each unique SOLID is saved as a separate STEP file in a dedicated subfolder.
  The transformation (translation and rotation) of each part is recorded and later used in the assembly.

- **Assembly Creation:**
  An assembly YAML file is generated, linking the parts (by file name) with their transformation data.
  This YAML file is then added to the project, finalizing the assembly import.

Example Log Output
^^^^^^^^^^^^^^^^^^

.. code-block:: text

   INFO: Detected an assembly with 5 parts.
   INFO: Saving parts in folder: ./my_assembly
   INFO: Imported part: my_assembly_part1 → my_assembly/my_assembly_part1.step
   INFO:   Location: [[tx, ty, tz], [rx, ry, rz], rotation_angle]
   INFO: Assembly 'my_assembly_assy' successfully added with 5 parts.

Notes
^^^^^

- The STEP file must contain more than one SOLID to be considered an assembly.
- If the file does not represent an assembly (i.e. only a single SOLID is found), the command will raise an error.
- The transformation data is recorded as a combination of translation and rotation (axis and angle),
  enabling precise placement of each part within the assembly.

Create an assembly
------------------

This is what PartCAD (or, at least, its VS Code Extension) is actually for.

Click ``Add an assembly file to the current package`` in the PartCAD Explorer
view. After that select an existing assembly file (`*.assy`) or enter a
filename for the new file to be created.

ASSY (Assembly YAML) files use the YAML syntax.
The list of parts has to be added as children under the ``links`` node.
Here is how an empty assembly file looks like:

  .. code-block:: yaml

    links:

Add a part to the assembly
--------------------------

Select the desired part or assembly in PartCAD Explorer.
After that navigate to the next line under "``links:``" and type "- pa"
(which is what you do when you want to add a child item with the name "part")
and, then, select the code completion suggestion from PartCAD.

.. image:: ./images/assy-autocompletion.png
  :width: 60%

This will add the selected part or assembly to the assembly file.

.. image:: ./images/assy-autocompletion-done.png
  :width: 60%

Inspect the assembly
--------------------

When you edit ASSY files in the current PartCAD package,
the assembly is displayed automatically on save.
Press ``Save`` (Ctrl-S or Cmd-S) to save the assembly file and trigger an
automatic inspection of the assembly. The ``OCP CAD Viewer`` view will appear on
the right if it's not open yet.
