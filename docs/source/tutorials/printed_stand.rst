##########################
A printed stand under load
##########################

This tutorial builds a small product end to end and asks it the question its designer would: *will it hold?* A
3D-printed stand, shaped like a table, carries a 100 mm block of steel in the middle of its top, as far from its legs
as it can be, where its weight bends the top the most. You will model the stand, say how it is printed, put the two
together in an assembly, show in a simulation that nothing moves, and turn what the simulation measured into a stress
analysis of the stand. Then you ask it two questions, one at a time. *Will it break?* A light print of it is at risk,
and printing it denser fixes that. *Will it bend too far?* It sags more than a table should, and no infill fixes that:
the shape has to change. Strength and stiffness are different questions, each with a fix of its own -- and you will
see both in the PartCAD IDE and on the command line, side by side.

Every step is done in the **PartCAD IDE**, the standalone application (see :doc:`/installation`); it works the same in
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
  the package; see :doc:`/ai_agents/skills`). It is optional: step 10 does the same by hand.

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

.. image:: ../images/tutorial-stand-01-package.png
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

The stand is six boxes: a top 200 by 120 mm and 2.8 mm thick, four legs 8 mm square and 60 mm long at its corners,
and a seat 20 mm square and 2 mm high in the middle of the top, which is what the block will stand on -- it touches
nothing else. The seat puts the whole of the block's weight in the middle of the top, more than 100 mm from every leg,
which is the hardest place for a table to carry it. Add them under ``parts:``, and join them with ``boolean`` parts -- a ``boolean`` combines exactly
two parts, so six boxes take five:

.. code-block:: yaml

  parts:
    top:
      type: basic
      cuboid: [200, 120, 2.8]
      offset: [[0, 0, 61.4], [0, 0, 1], 0]
    seat:
      type: basic
      cuboid: [20, 20, 2]
      offset: [[0, 0, 63.8], [0, 0, 1], 0]
    leg-1:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[-92, -52, 30], [0, 0, 1], 0]
    leg-2:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[92, -52, 30], [0, 0, 1], 0]
    leg-3:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[92, 52, 30], [0, 0, 1], 0]
    leg-4:
      type: basic
      cuboid: [8, 8, 60]
      offset: [[-92, 52, 30], [0, 0, 1], 0]
    tabletop:
      type: boolean
      operation: or
      parts: [top, seat]
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
      parts: [tabletop, legs]
      manufacturable: false       # a design is not made on its own: its print is
      parameters:
        material: {type: string, default: ":pla"}
      implements:
        foot:
          fl: [[-92, -52, 0], [0, 0, 1], 0]
          fr: [[92, -52, 0], [0, 0, 1], 0]
          br: [[92, 52, 0], [0, 0, 1], 0]
          bl: [[-92, 52, 0], [0, 0, 1], 0]
        pad: [[0, 0, 64.8], [0, 0, 1], 0]

``stand-design`` is what the designer has in mind: a solid table, made of PLA, with a foot under each leg and the pad
on top of its seat. Save the file and select ``stand-design`` in the PartCAD side bar: the Digital Thread opens on its
**Design > 3D** tab.

.. image:: ../images/tutorial-stand-02-design.png
  :alt: The stand's design in the Digital Thread's 3D view
  :align: center

========================
4. Say how it is printed
========================

The stand you will make is not the solid design: it is the design *printed* -- and printed light and fast, with two
walls, two solid layers top and bottom, and a sparse infill inside. Say so, under ``parts:``:

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
          topLayers: 2
          bottomLayers: 2
          infill: 10%

``stand`` has no ``type:`` and no file: it **is what the printer makes** of its design (see
:ref:`manufactured-parts`). PartCAD writes the route a printer would follow -- the same G-code ``pc cam :stand``
writes -- and follows it, bead by bead, so the part is the print, empty inside but for its infill, and it weighs what
the printer deposits: 39 grams, where the solid design would weigh 103. It is made of the design's PLA and has the
design's ports.

Select ``stand``. Its **3D** tab draws the print -- **Extra details**, last in the view panel, is ticked for a part --
and cut with a section from the view panel, its infill shows. While a slider moves, the view cuts what it already has
and the print looks solid; let go, and the cut print arrives (see :doc:`/digital_thread/lifecycle/design_3d`).

.. image:: ../images/tutorial-stand-03-print.png
  :alt: The printed stand in section, with its walls, skins and sparse infill
  :align: center

Its **CAM** tab shows the same print beside every setting of its printer, which you will come back to in step 14 (see
:doc:`/digital_thread/lifecycle/design_cam`).

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
and place the stand at the origin and the block on its seat -- the seat's upper face is 64.8 mm up, and the block's
origin is its centre, 50 mm above its bottom:

.. code-block:: yaml

  links:
    - part: stand
      name: stand
      location: [[0, 0, 0], [0, 0, 1], 0]
    - part: block
      name: block
      location: [[0, 0, 114.8], [0, 0, 1], 0]

Typing ``- pa`` in an ASSY file offers the part selected in the side bar (see :doc:`/tutorial`). Then declare the
assembly under ``assemblies:`` in ``partcad.yaml``:

.. code-block:: yaml

  assemblies:
    stand-with-block:
      type: assy
      path: stand-with-block.assy

.. image:: ../images/tutorial-stand-04-assembly.png
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
and pictures of before and after. Unfold **After**: the assembly is one rigid body of 7.889 kg -- the block and the
39 g of printed stand -- and its ``loads`` are what holds it up: a ``contact`` from the ``world`` of 77.39 N at its
four feet, against the ``gravity`` of the same.

.. image:: ../images/tutorial-stand-05-simulation.png
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
      mass: 7.88899347191
      loads:
      - kind: contact
        from: world
        force: [8.642051352785148e-13, 1.6117811709129956e-13, 77.39102616136282]
        contacts: 4
      - kind: gravity
        from: subject
        force: [0.0, 0.0, -77.3910259594371]

``--json`` prints the whole result instead, ``loads`` included, which is what a script or an agent reads.

.. image:: ../images/tutorial-stand-06-cli-simulation.png
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
            # Where it enters: the block's weight, 77.39 N on the floor less the
            # stand's own 0.38 N.
            pad: [0 N, 0 N, -77.01 N]
          # Its own weight.
          gravity: [0, 0, -9.81]

.. image:: ../images/tutorial-stand-07-scenario.png
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

==========================
11. One question at a time
==========================

The analysis passes a part only if it reports nothing, and it asks two questions. *Will it break?* The peak stress is
held to the material's yield strength over a safety factor of 1.5, and the material is the stand's PLA. *Will it bend
too far?* The part may move no more than ``max_displacement``, which is 1 mm unless told otherwise. Those are
different questions, with different answers and different fixes, so take them one at a time: switch the second off
for the stand. Under ``stand:``, above its ``fea:``, add:

.. code-block:: yaml

    stand:
      # ...
      # How far the stand may move under load, in millimetres: a setting of the
      # implementation behind every 'fea:' scenario below. null checks strength alone.
      cae:
        fea:
          max_displacement: null
      fea:
        stands:
          # ...

``fea:`` holds the stand's scenarios: what it is asked. ``cae: fea:`` holds the settings of the implementation that
answers every one of them -- the ``fea`` file type of the CalculiX package -- for the stand alone. ``null`` turns the
check off.

.. image:: ../images/tutorial-stand-08-sag-off.png
  :alt: The stand's cae section in partcad.yaml, with the displacement limit switched off
  :align: center

====================================================
12. Will it break? Run the analysis, and see it fail
====================================================

Select ``stand`` and open **Analysis > FEA**. Pick ``stands`` and press **Analyse**. The stand is meshed as its
design, and it is made of what its print is: two walls, two solid layers top and bottom and 10% infill deposit 38% of
the design's volume, so the analysis is handed PLA at 38% of its stiffness, strength and density. The log says so:

.. code-block:: text

  //:stand: analysed as its design, 'stand-design', at the 38% of it the printer deposits
  //:stand: Peak von Mises stress 16.2 MPa (129% of the allowable 12.6 MPa), peak displacement 10.3 mm, over 2331 elements

38% of PLA yields at 19 MPa, and the stand reaches 16.2 MPa holding the block: it holds it today, at six sevenths of
what breaks it, and a knock or a heavier block is the rest. That is what the safety factor is for -- the allowable is
12.6 MPa, and the stand is past it. The scenario is marked failed with a red cross, and the finding is under the
picture:

.. code-block:: text

  WARNING  The part does not reach the safety factor of 1.50: peak stress 16.2 MPa against an allowable 12.6 MPa.  (peak von Mises stress)

.. image:: ../images/tutorial-stand-09-fea-fails-strength.png
  :alt: The FEA tab: the scenario failed, short of its safety factor
  :align: center

The colours are the stress, from none (blue) to the peak of this run (red): they say *where* the stand works hardest
-- where the legs hold the top, and under the block -- not whether that is too much. The verdict says that. The log
line also says the top moves 10.3 mm; with the limit off, the verdict says nothing about it.

==============================================
13. ``pc qual test`` fails for the same reason
==============================================

The analysis is one of the checks ``pc qual test`` runs (``fea``), so what failed in the IDE fails a qualification
run, a commit hook or a CI job too:

.. code-block:: shell

  pc --no-ansi qual test -f fea :stand

.. code-block:: text

  ERROR:partcad:Qualification failed: //:stand: fea: //:stand: FEA 'stands' findings:
          WARNING The part does not reach the safety factor of 1.50: peak stress 16.2 MPa against an allowable 12.6 MPa.    (peak von Mises stress)

It exits with status 1.

.. image:: ../images/tutorial-stand-10-cli-fails-strength.png
  :alt: pc qual test failing in the IDE's terminal, on strength
  :align: center

=================================
14. Print it denser, and it holds
=================================

Open the stand's **Design > CAM** tab, set **infill** to 50% and press **Save** -- or change ``infill: 10%`` to
``infill: 50%`` in ``partcad.yaml``. With the section on, the CAM tab shows the denser inside before you save.

.. image:: ../images/tutorial-stand-11-cam.png
  :alt: The CAM tab with the infill raised to 50%
  :align: center

Run the check again:

.. code-block:: shell

  pc --no-ansi qual test -f fea :stand

.. code-block:: text

  //:stand: analysed as its design, 'stand-design', at the 65% of it the printer deposits
  //:stand: Peak von Mises stress 16.2 MPa (75% of the allowable 21.6 MPa), peak displacement 5.99 mm, over 2331 elements

The print now deposits 65% of the design -- 67 g of PLA rather than 39 -- so the same 16.2 MPa is 75% of an
allowable 21.6 MPa, and the run exits with status 0.

.. image:: ../images/tutorial-stand-12-cli-passes-strength.png
  :alt: pc qual test passing in the IDE's terminal, at 50% infill
  :align: center

===============================================
15. See it hold in the IDE, and look at the sag
===============================================

Back on **Analysis > FEA**, press **Analyse** again: the scenario's red cross is a tick, and there is no finding under
it. The picture's colours have barely changed, because the stress has not -- a denser stand carries the same block
the same way -- and what changed is how much of PLA's strength there is to carry it with.

.. image:: ../images/tutorial-stand-13-fea-passes-strength.png
  :alt: The FEA tab: the scenario passed at 50% infill
  :align: center

So the stand will not break. Whether it is good enough is the other question. The FEA tab colours the stress; how far
the part moves is in the line every run logs (step 14's, above): the middle of the top sinks 5.99 mm under the block.

======================================================
16. Will it bend too far? Say how far, and see it fail
======================================================

Six millimetres is a lot for a table 200 mm long: what stands on it leans, and what rolls, rolls to the middle. Hold
the top to 2 mm, a hundredth of its length, by setting the ``max_displacement`` line from step 11 to ``2``. (If you
saved the infill from the CAM tab, that line now reads ``max_displacement:`` with nothing after it: the tab writes the
file back, and an empty value is YAML's other spelling of ``null``.)

.. code-block:: yaml

      cae:
        fea:
          max_displacement: 2

Press **Analyse**: the scenario fails again, on how far it moves alone.

.. image:: ../images/tutorial-stand-14-fea-fails-sag.png
  :alt: The FEA tab: the scenario failed, sagging past 2 mm
  :align: center

``pc qual test`` says the same, and exits with status 1:

.. code-block:: text

  ERROR:partcad:Qualification failed: //:stand: fea: //:stand: FEA 'stands' findings:
          WARNING The part moves 5.99 mm under this load, past the 2 mm it is allowed.    (peak displacement)

.. image:: ../images/tutorial-stand-15-cli-fails-sag.png
  :alt: pc qual test failing in the IDE's terminal, on sag
  :align: center

Printing denser will not fix this one, and the numbers say why. The **stress** is the load spread over the shape,
and neither has changed: 16.2 MPa at 10% infill, at 50%, and at 100% too (the same analysis of a stand printed solid
says so). What the infill changes is what the stand may take -- an allowable of 12.6, 21.6 and 32.9 MPa. The **sag**
is the load over the stiffness, and the stiffness is the material's modulus times the shape. The modulus scales with
what the printer deposits: the top sags 10.3 mm at 38% of the design, 5.99 mm at 65%, and printed solid, at 99%,
still 3.94 mm. The fraction stops at 100%, so this shape cannot get under 2 mm however it is printed. The shape has
to change.

========================
17. Make the top thicker
========================

A plate's sag goes roughly with one over its thickness cubed, so thickness is the cheap way to stiffness: a top 6 mm
thick is (6 / 2.8)\ :sup:`3`, about ten times, as stiff as one 2.8 mm thick. Thicken it downwards, so that its upper
face, the seat, the block and the ports all stay where they are. In ``top:``, change two numbers:

.. code-block:: yaml

    top:
      type: basic
      cuboid: [200, 120, 6]
      offset: [[0, 0, 59.8], [0, 0, 1], 0]

The top now reaches 3.2 mm down over the legs; ``stand-design`` is the union of the two, so the overlap is simply
gone. Nothing else changes: the assembly, the simulation and the scenario stay as they are, and the load is still the
block's weight.

.. image:: ../images/tutorial-stand-16-thicker-top.png
  :alt: The thicker top in partcad.yaml, and the design in the 3D view
  :align: center

============================================
18. Pass, on the command line and in the IDE
============================================

.. code-block:: shell

  pc --no-ansi qual test -f fea :stand

.. code-block:: text

  //:stand: analysed as its design, 'stand-design', at the 58% of it the printer deposits
  //:stand: Peak von Mises stress 6.83 MPa (35% of the allowable 19.4 MPa), peak displacement 1.09 mm, over 2511 elements

It exits with status 0. A thicker top is stiffer and stronger both: the stress falls to 6.83 MPa, a third of what
the stand may take, and the top sags 1.09 mm, a little over half of what it may. The thicker top prints sparser, at
58% of the design rather than 65%, and still the print weighs 115 g where it weighed 67: stiffness is paid for in
plastic, as strength was.

.. image:: ../images/tutorial-stand-17-cli-passes.png
  :alt: pc qual test passing in the IDE's terminal, with the thicker top
  :align: center

On **Analysis > FEA**, press **Analyse**: the tick is back, with no finding under it. The colours have changed this
time, because the shape has. They still run from nothing to this run's own peak, and the peak has moved: the thick top
is mostly blue, and what works hardest now is the legs, just under the top.

.. image:: ../images/tutorial-stand-18-fea-passes.png
  :alt: The FEA tab: the scenario passed with the thicker top
  :align: center

================
Where to go next
================

* :ref:`manufactured-parts` -- parts that are what their machine makes: prints, cut parts, moldings, and ``pc cam
  --materialize``.
* :ref:`additive` -- every printer setting, and what each one does to the route.
* :ref:`cae-section` and :ref:`pc cae <cae>` -- analyses, their scenarios and their implementations.
* :doc:`/digital_thread/lifecycle/simulation` -- simulations, and how their verdicts are judged.

=================
The whole package
=================

``partcad.yaml`` as it stands at the end of the tutorial -- the top 6 mm thick, printed at 50% infill, held to a
2 mm sag:

.. literalinclude:: ../../../dev-tools/screenshots/tutorial-stand/partcad.yaml
  :language: yaml
  :lines: 5-

and ``stand-with-block.assy``:

.. literalinclude:: ../../../dev-tools/screenshots/tutorial-stand/stand-with-block.assy
  :language: yaml
