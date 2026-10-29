Requirements
############

A requirement is what the object was asked to be, written from the point of view
of whoever asked for it and before anybody designs anything. It is the first
link of the thread and the one everything else is held to: the design is judged
against it, the analyses and simulations are evidence for it, and validation is
the question whether it is met.

What PartCAD captures
=====================

A part, an assembly, a scene or a sketch may declare a ``requirements:``
section. :ref:`requirements` describes it in full; in short, it has two halves,
which are checked two ways:

.. code-block:: yaml

  parts:
    bracket:
      requirements:
        features:                       # prose: a name and a sentence each
          mounting: Four M3 clearance holes on a 40 mm square, reachable from the top
          shelf-load: Holds a 2 kg shelf at its free end without visible bending
        ports:                          # measured
          top: [null, [0, 0, -1], null] # faces down, anywhere
        interfaces:
          m3-thru: null                 # implemented, anywhere
        physics:
          mass: "<0.05"                 # kg
      simulate:
        holds-the-shelf:
          feature: shelf-load           # the feature this simulation demonstrates
          ...

``features``
  What the object has to have or do, in the words of whoever asked. A feature is
  a sentence, not a number, and no program can measure it: it is judged from
  evidence -- a simulation that names it, a view in which it can be seen, a line
  of the bill of materials -- by a person or by the ``/pc:validate`` agent skill.

``ports``, ``interfaces`` and ``physics``
  What PartCAD can measure: a port that has to be there and face a given way,
  an interface that has to be implemented and where, a physical property that
  has to have a value. Any part of each may be ``null`` -- no requirement -- and
  a value may be a constant, a comparison (``>0``, ``<=1``, ``!0``) or several
  of them. ``pc test`` checks every one of them, every time.

A ``simulate:`` entry names the feature it demonstrates with ``feature:``, which
is how a simulation becomes evidence for a requirement rather than a test that
happens to exist.

Writing requirements first
==========================

Requirements written after the design describe the design, and then everything
meets them. They are worth having when they are written first, from the
description, in its own terms -- "four M3 holes on a 40 mm square" rather than
"the holes in sketch 3". The ``/pc:gen-part`` and ``/pc:gen-assembly`` agent
skills do exactly that before they model anything; written by hand, the same
order holds.

Keep to what was asked for. A requirement the design imposes on itself -- a
stock size, a tool -- belongs to manufacturing, not here.

In the UI
=========

An object that declares requirements gets a **Requirements** tab in front of all
the others. It is the one tab with no strip of its own -- there is nothing to
divide it into, because a requirement is one thing either met or not.

It lists every port, interface and physical property required, each with a green
or a red mark from the same check ``pc test`` runs, and then a table of the
features. Each feature carries its description and a banner per thing that
validates it: one for every simulation that names it with ``feature:``, one for
every analysis scenario that does (**FEA: loaded**), and an **LLM** banner --
"Validate using /pc-validate" -- since a sentence is for an agent or a person to
judge and for no program to measure.

.. image:: /images/dt-requirements.png
  :width: 100%
  :align: center
  :alt: The Requirements tab: the measured requirements with their marks, and the features with what validates each

``pc ide view`` has a flag per tab of the five groups and none for this one:
the tab is there for an object that declares ``requirements:`` and absent for
every other object, so there is nothing to ask for.

On the command line
===================

- ``pc test`` runs the ``requirements`` check (see :ref:`test-requirements`):
  every measured requirement, with what was found instead of each one not met. A
  value PartCAD cannot find out -- a mass with no density to work it out from --
  fails as "not known" rather than passing.
- ``pc sim`` runs every simulation, including those that name a feature.
- ``/pc:validate`` gathers the rest of the evidence -- renders from every angle
  that matters, the bill of materials and the assembly instructions -- and gives
  each requirement a verdict. See :doc:`/digital_thread/lifecycle/validation`.

``pc info`` prints the section as it is read, which is how to see what a template
or an :ref:`enrich <part-types>` left behind. ``pc lint`` reports a ``requirements:``
that is malformed before anything is built.

Agent skills
============

``/pc:gen-part`` and ``/pc:gen-assembly``
  Write the ``requirements:`` down first, from the description and in its own
  terms, and only then model anything. This is the order that makes requirements
  worth having, and it is the reason to generate from a description rather than
  to describe what was generated.

``/pc:validate``
  Gives every requirement a verdict -- met, not met, or "cannot tell" -- and
  names the evidence for each. It is the only one of the skills that judges the
  ``features:`` half, because a sentence is what an agent or a person can read
  and a program cannot measure.
