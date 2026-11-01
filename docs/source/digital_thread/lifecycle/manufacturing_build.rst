.. _dt-manufacturing-build:

#####
Build
#####

**Build** is what is made, in the order it is made in. Where
:doc:`Build vs Buy </digital_thread/lifecycle/manufacturing_bvb>` is the
decision, this is the plan that follows from it: a list of steps, and for the
one selected, its page of the instructions -- how to make a part, or how to add
a link to the assembly.

In the UI
=========

The order is the order of making: a part's **stock** first and the part itself
last; an assembly's links in the order the ASSY file gives them, with each
built part preceded by the step that makes it, and -- with **Recursively** --
each built sub-assembly before the step that adds it.

Selecting a step shows its page: the manufacturing instructions for a part, with
its **route** drawn where the part declares one, or the step that joins a link
to what is already there.

.. image:: /images/dt-manufacturing-build.png
  :width: 100%
  :align: center
  :alt: The Manufacturing group's Build tab: the order to make it in, with the selected step's page

The steps and their order are the very ones ``pc instructions`` writes, so a
step selected here and a page of that file are the same step.

On the command line
===================

.. code-block:: shell

  pc ide view --manufacturing-build :robot      # the tab itself
  pc instructions -b robot                      # the same steps, with how to make each built part
  pc cam :panel                                 # the program a machine cuts a part with
  pc info :panel                                # the stock, the method and the tolerances it resolved to

.. _cam-routes:

Machine routes: ``pc cam``
==========================

An object can say what is cut out of it and how, and ``pc cam`` writes the
program a machine does it with. The job lives on the object, in its
``manufacturing:`` section, because it is a property of the object rather than
of whoever cuts it -- a panel is 18 mm thick and has to be cut through
whichever router is asked:

.. code-block:: yaml

  # partcad.yaml

  parts:
    panel:
      type: build123d
      path: panel.py
      manufacturing:
        method: subtractive
        source: sheet         # the stock it is cut out of
        cnc:
          operation: profile  # around the outside of it, and inside every hole
          diameter: 6 mm      # the cutter
          depth_per_pass: 3 mm
          feed: 2400 mm/min
          speed: 18000 rpm

Saying something about being cut is the object's **opt-in**, and the whole of
it. ``pc cam`` with nothing named produces a route for every sketch and part of
the package that declares one and passes over every object that does not,
silently -- most objects are never cut, and a package where three parts of forty
are is the ordinary case rather than thirty-seven warnings. Naming an object
that declares nothing is an error, because naming one is asking about it.

Unlike a solver, PartCAD **ships an implementation**: ``//builtin/cam`` writes
G-code, and ``camImplementation`` names it by default. A route is arithmetic on
the object's own outline rather than somebody else's program with a release
cycle of its own, which is the test ``export:`` and ``render:`` already pass and
``cae:`` does not -- so it ships here for the same reason DXF does. A controller
that wants a dialect of its own is a package declaring a file type in its own
``cam:`` section (see :ref:`cam-section`), named by that option, by the object's
own ``implementation:``, or by ``-i`` for one run.

Every key of the object's section is also a parameter of that file type, which
makes the two of them three layers of one namespace: the built-in package
underneath, the package's own ``cam:`` section, then the object's
``manufacturing:``. A package cutting twenty parts from one sheet sets the tool
once; the one part that needs a smaller cutter says so for itself. Lengths,
feeds and speeds may each carry a unit and are converted at every layer, so a
``mm/min`` written by the package is understood as surely as one written on the
object.

What comes back is a file beside the package -- ``panel.nc`` -- and what it
counted: how many passes, how deep, how far the tool travels in the cut. The
route is the object's outline **sectioned at the bottom of the cut**, offset by
the radius of the cutter, and that is both what makes it right for a prismatic
object and the limit worth knowing about every other one: where the
cross-section changes over the cut, no single outline is right, and the route
follows the bottom and says so as a warning naming how much the two ends differ
by. A route produced from an outline nobody expected is the one failure that
looks like a success all the way to the machine.

``pc test`` runs the same thing as its ``cam`` check -- it produces the route
and passes the object only if one came back -- and applies it to an object that
declares the section and to nothing else, so a package of bolts pays nothing for
it. Unlike the analyses it does not keep what it produced: a route a check wrote
would be indistinguishable from the one ``pc cam`` writes, so it routes into a
temporary directory and deletes it.

The check that used to be called ``cam`` is ``manufacturability``. It asks
whether an object can be made or bought *at all* -- whether its geometry suits
the method it declares, whether what it is made from is reproducible, whether a
supplier could be found -- which is a different question from whether a
post-processor can produce a program for it. One word answered both until
``pc cam`` existed. ``-f`` filters by name prefix, so ``-f manufacturability``
selects that check and its seven method-specific siblings and ``-f cam``
selects the route check alone.

`examples/feature_cam <https://github.com/partcad/partcad/tree/main/examples/feature_cam>`_
is the three operations on three objects, and a fourth that declares no section
and is passed over. See :ref:`pc cam <cam>` for the command and the units it
accepts.

Agent skills
============

``/pc:export`` and ``/pc:convert``
  Write the file a machine or a shop is given, in the format it asks for.

``/pc:validate``
  Reads the assembly instructions these steps become, as part of giving a
  requirement its verdict.
