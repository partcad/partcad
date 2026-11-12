####################################
Tutorial: a printed stand under load
####################################

This tutorial builds a small product end to end and asks it the question its designer would: *will it hold?* A
3D-printed stand, shaped like a table, carries a 100 mm block of steel. You will model the stand, say how it is
printed, put the two together in an assembly, show in a simulation that nothing moves, turn what the simulation
measured into a stress analysis of the stand, watch the stand fail it at a low infill, and make it pass by printing it
denser -- in the PartCAD IDE and on the command line, side by side.

Every step is done in the **PartCAD IDE**, the standalone application (see :doc:`installation`); it works the same in
Visual Studio Code or VSCodium with the PartCAD extension. The screenshots are of the IDE.

.. contents:: Steps
  :local:
  :depth: 1

================
Before you start
================

You need:

* PartCAD, with ``pc`` on the ``PATH`` (``pc version`` answers), and the PartCAD IDE.
* An internet connection the first time: the simulation and the analysis are plugins from the public index
  (``//pub/feature/simulate/mujoco`` and ``//pub/feature/cae/calculix``), installed into sandboxes of their own when
  they are first used.
* `CalculiX <http://www.calculix.de/>`_'s solver, ``ccx``, unless PartCAD runs the analysis in a container (it does
  where Docker is available). On Debian and Ubuntu: ``sudo apt-get install calculix-ccx``.
* For step 9, `Claude Code <https://claude.com/claude-code>`_ with PartCAD's skills (``pc init`` installs them into
  the package; see :doc:`ai_agents/skills`). It is optional: step 10 does the same by hand.

=================================
1. Create the package and open it
=================================

.. code-block:: shell

  mkdir printed-stand
  cd printed-stand
  pc init
  pc ide workspace .

``pc init`` writes a ``partcad.yaml`` that depends on the public index (``pub``), and ``pc ide workspace`` opens the
directory in the IDE, in the PartCAD workbench.

.. image:: ./images/tutorial-stand-01-package.png
  :alt: The PartCAD IDE with the new, empty package open
  :align: center

================================================
2. Say what it is made of, and where it connects
================================================

Open ``partcad.yaml``. ``pc init`` wrote a ``sketches:``, a ``parts:`` and an ``assemblies:`` section, each with
nothing in it but comments; the rest of this tutorial adds to those rather than writing them again. Add two materials
and two interfaces as sections of their own:

.. code-block:: yaml

  materials:
    pla:
      formal: PLA
      density: 1240               # kg/m^3
      mu: 0.5
      youngsModulus: 3.5e+9       # Pa
      poissonsRatio: 0.36
      yieldStrength: 5.0e+7       # Pa
    steel:
      formal: Steel
      density: 7850
      mu: 0.6

  interfaces:
    foot:
      desc: The bottom of a leg, standing on the floor.
      ports:
        foot:
    pad:
      desc: Where the block sits on the top.
      ports:
        pad:

A material's density is what every part made of it weighs; its stiffness (``youngsModulus``) and its strength
(``yieldStrength``) are what an analysis of such a part is handed (see :ref:`materials`). An interface is a kind of
place where something connects: the stand will have a ``foot`` under each leg and a ``pad`` in the middle of its top,
and the analysis in step 9 will hold the stand by the first and load it at the second.

===================
3. Model the design
===================

The stand is five boxes: a top 120 by 80 mm and 4 mm thick, and four legs 8 mm square and 60 mm long. Add them under
``parts:``, and join them with ``boolean`` parts -- a ``boolean`` combines exactly two parts, so five boxes take four:

.. code-block:: yaml

  parts:
    top:
      type: basic
      cuboid: [120, 80, 4]
      offset: [[0, 0, 62], [0, 0, 1], 0]
    leg-1:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[-52, -32, 30], [0, 0, 1], 0]
    leg-2:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[52, -32, 30], [0, 0, 1], 0]
    leg-3:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[52, 32, 30], [0, 0, 1], 0]
    leg-4:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[-52, 32, 30], [0, 0, 1], 0]
    legs-front:
      type: boolean
      operation: or
      parts: [leg-1, leg-2]
    legs-back:
      type: boolean
      operation: or
      parts: [leg-3, leg-4]
    legs:
      type: boolean
      operation: or
      parts: [legs-front, legs-back]
    stand-design:
      type: boolean
      operation: or
      parts: [top, legs]
      manufacturable: false       # a design is not made on its own: its print is
      parameters:
        material: {type: string, default: ":pla"}
      implements:
        foot:
          fl: [[-52, -32, 0], [0, 0, 1], 0]
          fr: [[52, -32, 0], [0, 0, 1], 0]
          br: [[52, 32, 0], [0, 0, 1], 0]
          bl: [[-52, 32, 0], [0, 0, 1], 0]
        pad: [[0, 0, 64], [0, 0, 1], 0]

``stand-design`` is what the designer has in mind: a solid table, made of PLA, with a foot under each leg and the pad
on its top. Save the file and select ``stand-design`` in the PartCAD side bar: the Digital Thread opens on its
**Design > 3D** tab.

.. image:: ./images/tutorial-stand-02-design.png
  :alt: The stand's design in the Digital Thread's 3D view
  :align: center

========================
4. Say how it is printed
========================

The stand you will make is not the solid design: it is the design *printed*, with two walls, a few solid layers top
and bottom, and a sparse infill inside. Say so, under ``parts:``:

.. code-block:: yaml

    stand:
      desc: The stand, printed
      parameters:
        tolerance: {type: float, default: 0.2}
      manufacturing:
        method: additive
        source: stand-design      # the design it is a print of
        fff:                      # a filament printer
          layerHeight: 0.2 mm
          walls: 2
          infill: 10%

``stand`` has no ``type:`` and no file: it **is what the printer makes** of its design (see
:ref:`manufactured-parts`). PartCAD writes the route a printer would follow -- the same G-code ``pc cam :stand``
writes -- and follows it, bead by bead, so the part is the print, empty inside but for its infill, and it weighs what
the printer deposits: 30 grams, where the solid design would weigh 67. It is made of the design's PLA and has the
design's ports.

Select ``stand``. Its **3D** tab draws the print -- **Extra details**, last in the view panel, is ticked for a part --
and cut with a section from the view panel, its infill shows. While a slider moves, the view cuts what it already has
and the print looks solid; let go, and the cut print arrives (see :doc:`digital_thread/lifecycle/design_3d`).

.. image:: ./images/tutorial-stand-03-print.png
  :alt: The printed stand in section, with its walls, skins and sparse infill
  :align: center

Its **CAM** tab shows the same print beside every setting of its printer, which you will come back to in step 13 (see
:doc:`digital_thread/lifecycle/design_cam`).

.. tip::

  ``pc cam --materialize :stand`` writes the print into ``stand.brep`` (and its route into ``stand.nc``). From then on
  the file is the part, read rather than worked out, and ``pc qual test`` checks that it is still what the printer
  makes. Nothing in this tutorial needs it.

==================
5. The steel block
==================

.. code-block:: yaml

    block:
      type: basic
      cuboid: 100
      parameters:
        material: {type: string, default: ":steel"}

A 100 mm cube of steel weighs 7.85 kg.

===================================
6. Put them together in an assembly
===================================

An assembly is a file of its own. Create ``stand-with-block.assy`` beside ``partcad.yaml`` (**File > New File...**),
and place the stand at the origin and the block on its top -- the top's upper face is 64 mm up, and the block's
origin is its centre, 50 mm above its bottom:

.. code-block:: yaml

  links:
    - part: stand
      name: stand
      location: [[0, 0, 0], [0, 0, 1], 0]
    - part: block
      name: block
      location: [[0, 0, 114], [0, 0, 1], 0]

Typing ``- pa`` in an ASSY file offers the part selected in the side bar (see :doc:`tutorial`). Then declare the
assembly under ``assemblies:`` in ``partcad.yaml``:

.. code-block:: yaml

  assemblies:
    stand-with-block:
      type: assy
      path: stand-with-block.assy

.. image:: ./images/tutorial-stand-04-assembly.png
  :alt: The block standing on the printed stand
  :align: center

========================================
7. Show that nothing moves -- in the IDE
========================================

A simulation drops the assembly onto a floor, lets it settle for two seconds, and judges what happened. Add one to
the assembly's declaration:

.. code-block:: yaml

  assemblies:
    stand-with-block:
      type: assy
      path: stand-with-block.assy
      qual:
        sim:
          stands:
            desc: The stand holds the block, and nothing moves
            path: //pub/feature/simulate/mujoco:mujoco
            params:
              duration: 2.0
            # Every body ends within 2 mm of where it started.
            validation: |
              max(
                  sum((a - b) ** 2 for a, b in zip(after["bodies"][name]["pos"], before["bodies"][name]["pos"])) ** 0.5
                  for name in before["bodies"]
              ) < 2.0

Select ``stand-with-block`` and open **Qualification > Simulation**. Run ``stands``: it passes, with the run's video
and pictures of before and after. Unfold **After**: the assembly is one rigid body of 7.881 kg -- the block and the
30 g of printed stand -- and its ``loads`` are what holds it up: a ``contact`` from the ``world`` of 77.31 N at its
four feet, against the ``gravity`` of the same.

.. image:: ./images/tutorial-stand-05-simulation.png
  :alt: The simulation tab: the run passed, and the forces at its end
  :align: center

A print is simulated as its design's outside and weighed as the print: a rigid body collides with its outside, and a
print's beads would be far more triangles than a physics engine reads from one mesh.

================================
8. The same, on the command line
================================

Open a terminal in the IDE (**Terminal > New Terminal**) and run the same simulation, writing its end state to a file:

.. code-block:: shell

  pc --no-ansi qual test --simulation -a stand-with-block -f stands --after after.yaml

.. code-block:: yaml

  bodies:
    subject:
      mass: 7.88060885829
      loads:
      - kind: contact
        from: world
        force: [0.0, 0.0, 77.30877289982494]
        contacts: 4
      - kind: gravity
        from: subject
        force: [0.0, 0.0, -77.3087728998249]

``--json`` prints the whole result instead, ``loads`` included, which is what a script or an agent reads.

.. image:: ./images/tutorial-stand-06-cli-simulation.png
  :alt: The simulation run in the IDE's terminal
  :align: center

===========================================================
9. Turn the simulation into an analysis -- with Claude Code
===========================================================

The simulation says what holds the assembly up; it cannot say what that does to the stand, which is rigid there. A
stress analysis can, given the loads. PartCAD's ``sim-assembly-fea`` skill works them out from the simulation: in
Claude Code, in this package, run

.. code-block:: text

  /pc:sim-assembly-fea stand-with-block stands stand

It runs ``stands``, reads the loads at its end in the stand's own frame (its helper, ``part_loads.py``, does the
arithmetic), and works out what they do to the stand: the stand and the block are one body, so the block's weight
passes through the stand -- in at the pad, out at the four feet. It adds the stand an FEA scenario named after the
simulation, holding the stand where the load leaves it and loading it where the load enters, and runs it:

.. code-block:: yaml

    stand:
      # ...
      fea:
        stands:
          desc: At rest at the end of 'stands', holding the block on its top
          implementation: //pub/feature/cae/calculix:fea
          # Where the load leaves it: the floor, under its four feet.
          fix: [foot]
          load:
            # Where it enters: the block's weight, 77.31 N on the floor less the
            # stand's own 0.30 N.
            pad: [0 N, 0 N, -77.01 N]
          # Its own weight.
          gravity: [0, 0, -9.81]

.. image:: ./images/tutorial-stand-07-scenario.png
  :alt: The FEA scenario the skill added, in partcad.yaml
  :align: center

==================================
10. Or write the analysis yourself
==================================

Without Claude Code, write the same scenario under ``stand:`` in ``partcad.yaml``. The editor checks it against
PartCAD's schema as you type. What each key says:

* ``fea:`` holds named **scenarios**, each one set of conditions; a part may have several.
* ``implementation:`` is who runs it: the CalculiX package from the public index.
* ``fix:`` lists the interfaces whose ports are held still -- every ``foot``.
* ``load:`` puts a force on a port: an interface, then the force, as a magnitude (``77 N``, pulling straight down) or
  as a vector in the part's frame.
* ``gravity:`` adds the part's own weight.
* ``params:`` re-tunes the implementation for this scenario alone.

The analysis passes a part only if it reports nothing. Its steel defaults are replaced by the stand's PLA, and how far
the part may move is one of its parameters. Say it out loud -- the top may not sag more than a millimetre:

.. code-block:: yaml

          params:
            max_displacement: 1.0     # mm

.. image:: ./images/tutorial-stand-08-yaml.png
  :alt: Editing the FEA scenario in partcad.yaml
  :align: center

=======================================
11. Run the analysis, and watch it fail
=======================================

Select ``stand`` and open **Analysis > FEA**. Pick ``stands`` and press **Analyse**. The stand is meshed as its
design, and it is made of what its print is: 10% infill and two walls deposit 46% of the design's volume, so the
analysis is handed PLA at 46% of its stiffness, strength and density. The log says so:

.. code-block:: text

  //:stand: analysed as its design, 'stand-design', at the 46% of it the printer deposits
  //:stand: Peak von Mises stress 7.83 MPa, peak displacement 1.13 mm, over 3297 elements

The stress is far below what 46% of PLA can take, but the top sags 1.13 mm under the block: the scenario is marked
failed with a red cross, and the finding is under the picture:

.. code-block:: text

  WARNING  The part moves 1.13 mm under this load, past the 1 mm it is allowed.  (peak displacement)

.. image:: ./images/tutorial-stand-09-fea-fails.png
  :alt: The FEA tab: the scenario failed, sagging past what it is allowed
  :align: center

The colours are the stress, from none (blue) to the peak of this run (red): they say *where* the stand works hardest
-- under the block -- not whether that is too much. The verdict says that.

==============================================
12. ``pc qual test`` fails for the same reason
==============================================

The analysis is one of the checks ``pc qual test`` runs (``fea``), so what failed in the IDE fails a qualification
run, a commit hook or a CI job too:

.. code-block:: shell

  pc --no-ansi qual test -f fea :stand

.. code-block:: text

  ERROR:partcad:Qualification failed: //:stand: fea: //:stand: FEA 'stands' findings:
          WARNING The part moves 1.13 mm under this load, past the 1 mm it is allowed.    (peak displacement)

It exits with status 1.

.. image:: ./images/tutorial-stand-10-cli-fails.png
  :alt: pc qual test failing in the IDE's terminal
  :align: center

=============================
13. Print it denser, and pass
=============================

Open the stand's **Design > CAM** tab, set **infill** to 40% and press **Save** -- or change ``infill: 10%`` to
``infill: 40%`` in ``partcad.yaml``. With the section on, the CAM tab shows the denser inside before you save.

.. image:: ./images/tutorial-stand-11-cam.png
  :alt: The CAM tab with the infill raised to 40%
  :align: center

Run the check again:

.. code-block:: shell

  pc --no-ansi qual test -f fea :stand

The print now deposits 63% of the design, the top sags 0.82 mm, and the run exits with status 0.

.. image:: ./images/tutorial-stand-12-cli-passes.png
  :alt: pc qual test passing in the IDE's terminal
  :align: center

==============================
14. And see it pass in the IDE
==============================

Back on **Analysis > FEA**, press **Analyse** again: the scenario's red cross is a tick, and there is no finding under
it. The picture's colours have barely changed, because the stress has not -- a stiffer stand carries the same block
the same way -- and what changed is how far it bends, and the verdict.

.. image:: ./images/tutorial-stand-13-fea-passes.png
  :alt: The FEA tab: the scenario passed
  :align: center

================
Where to go next
================

* :ref:`manufactured-parts` -- parts that are what their machine makes: prints, cut parts, moldings, and ``pc cam
  --materialize``.
* :ref:`additive` -- every printer setting, and what each one does to the route.
* :ref:`cae-section` and :ref:`pc cae <cae>` -- analyses, their scenarios and their implementations.
* :doc:`digital_thread/lifecycle/simulation` -- simulations, and how their verdicts are judged.

==================
The whole package
==================

``partcad.yaml`` as it stands at step 11, before the infill is raised:

.. literalinclude:: ../../dev-tools/screenshots/tutorial-stand/partcad.yaml
  :language: yaml
  :lines: 5-

and ``stand-with-block.assy``:

.. literalinclude:: ../../dev-tools/screenshots/tutorial-stand/stand-with-block.assy
  :language: yaml
