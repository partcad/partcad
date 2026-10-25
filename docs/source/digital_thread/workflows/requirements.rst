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

In the Digital Thread
=====================

An object that declares requirements gets a **Requirements** tab in front of all
the others. It lists every port, interface and physical property required, each
with a green or a red mark from the same check ``pc test`` runs, and then a
table of the features: each with its description, a banner for every simulation
that names it, and an **LLM** banner -- "Validate using /pc-validate" -- since a
feature is for an agent or a person to judge.

How requirements are checked
============================

- ``pc test`` runs the ``requirements`` check (see :ref:`test-requirements`):
  every measured requirement, with what was found instead of each one not met. A
  value PartCAD cannot find out -- a mass with no density to work it out from --
  fails as "not known" rather than passing.
- ``pc sim`` runs every simulation, including those that name a feature.
- ``/pc:validate`` gathers the rest of the evidence -- renders from every angle
  that matters, the bill of materials and the assembly instructions -- and gives
  each requirement a verdict. See :doc:`/digital_thread/workflows/validation`.
