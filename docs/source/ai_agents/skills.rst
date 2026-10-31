######
Skills
######

PartCAD ships a library of `Agent Skills <https://code.claude.com/docs/en/skills>`_ -- a directory of
``SKILL.md`` files, each one a procedure an AI coding agent follows to do a job with PartCAD. They are
vendor-neutral: anything that reads ``SKILL.md`` can use them.

They are not a different PartCAD. Each skill runs the same commands documented in :doc:`/cli`, so nothing a
skill produces depends on the agent that produced it, and anything a skill does you can do by hand.

=================
Getting them
=================

The skills ship inside the ``partcad`` wheel, so if you have PartCAD you have them:

.. code-block:: shell

  pc init                 # creates a package and installs the skills into the repository
  pc init --skills-only   # installs the skills into a repository that already has a package
  pc init --no-skills     # skips them

``pc init`` writes the Claude Code plugin into the repository and ``pc-``-prefixed copies into
``.cursor/skills``, so an agent opening that repository finds them with nothing to install. :doc:`/ai_agents/plugins`
covers the other way in -- installing the published plugin into the agent instead of into the repository.

Re-running ``pc init`` updates the installed copies and **removes the skills PartCAD has stopped shipping**.
A retired skill left behind goes on describing a command line that has moved, and an agent follows it anyway.
Under ``.cursor/skills`` only copies PartCAD stamped are removed, since the ``pc-`` prefix is not proof of
authorship.

``pc healthcheck`` reports installed skills that came from an older PartCAD than the one now installed:
``pc upgrade`` replaces PartCAD and leaves the skills where they are, so something has to notice.


========================
The skills PartCAD ships
========================

Fourteen of them. The name in each heading is what you type in Claude Code; under
Cursor the same skill is ``pc-<name>``, and an agent that chooses skills by their
description will reach for the right one without being told.


Setting up
==========

``/pc:setup``
  Puts ``pc`` on this machine so the other skills have something to run, and
  does nothing if a working one is already there -- the first thing it does is
  check, because the common case is that PartCAD is installed and the agent
  should get on with the job.

  It installs one of two ways and asks which if it matters: the **standalone
  build** from the GitHub releases, which carries its own Python and needs none
  on the machine, or the **wheel** into the Python environment that is currently
  active, which is the one to pick if anything is going to ``import partcad``.
  When the agent is running inside Visual Studio Code or VSCodium it also
  installs the PartCAD extension into that editor -- and works out which editor
  it is in rather than guessing, stopping early when there is nothing to do.

``/pc:init``
  Creates a package in the current directory by running ``pc init``, which writes
  a ``partcad.yaml`` and installs the skills into the repository. It locates the
  command first and falls back to ``/pc:setup`` when there is nothing installed.


Generating geometry
===================

``/pc:gen``
  The one to use when it does not matter which kind of object the request is.
  It decides whether what was asked for is a single part, a multi-part assembly
  or a 2D sketch, and then follows the matching skill below. "Model me a shelf
  bracket" is a part; "model me a gearbox" is an assembly; "draw me the profile"
  is a sketch.

``/pc:gen-part``
  Models one part from a description, and the order it works in is the point:

  1. It reads the request, and chooses a representation -- build123d, CadQuery,
     OpenSCAD, or a primitive -- rather than defaulting to one.
  2. **It writes down what the part is required to be before it writes any
     geometry**, as the ``requirements:`` section, in the terms of the request
     ("four M3 holes on a 40 mm square") rather than in terms of the model it is
     about to build. Requirements written afterwards describe the design, and
     then everything meets them.
  3. It authors and registers the script, then validates it with ``pc test``.
  4. It renders the part **from several angles and compares each view against
     the description**, because a single projection hides whatever is behind it
     -- then iterates on what the comparison found.

  When the PartCAD IDE (or VS Code with the PartCAD extension) is running beside
  the agent, every version of the part that builds and renders is also shown in
  the Digital Thread's 3D view as soon as it does. Each one takes up the turn of
  the one before, so you watch the part take shape rather than a series of
  restarts. A version that fails is never shown: the view holds the last one that
  worked.

``/pc:gen-assembly``
  Models an assembly, and is the longest of the skills because putting things
  together is where the hard-won rules live. It decomposes the request, takes an
  inventory of parts that already exist and generates only what is missing,
  authors the ``.assy``, and groups whatever repeats into sub-assemblies.

  Its last step is the valuable one: it **replaces the coordinates it started
  with by connections**, so the assembly ends up saying what holds each item
  rather than where each item happens to sit. That is what makes the assembly
  survive a change to one of its parts. The rules it follows there are the ones
  that are easy to get wrong -- find the pairs by where the ports actually are;
  grow the order outwards from what is already placed rather than following the
  order the thing is built in; the first item needs no location at all; a turn is
  a *difference* between two ports, not an orientation; let sub-assemblies join
  each other; and, above all, **do not predict a mate -- try it**, and look at
  the result.

  Beside an IDE it shows its progress the way ``/pc:gen-part`` does: each part it
  generates as it takes shape, then every version of the assembly that builds
  and renders, all on one continuous turn of the 3D view.

``/pc:gen-sketch``
  Authors a 2D sketch -- build123d, CadQuery, DXF, SVG or a basic outline -- and
  validates it by rendering it to SVG and comparing that against the
  description. Sketches are what parts are extruded and swept from, and what a
  port's boundary is drawn with.

``/pc:add-interfaces``
  Adds ``interfaces``, ports and ``implements:`` to a part that has none, so that
  PartCAD can mate it by connection instead of by hand-written coordinates.

  It works the port positions out of the geometry -- by rendering the part and
  by reading its source -- and then **proves them twice**: by drawing the ports
  on the part and looking at them, and by mating two instances of the part in a
  throwaway assembly and looking at that. A port that is in the wrong place or
  facing the wrong way is invisible in the declaration and obvious in either
  picture.


Finding and describing
======================

``/pc:search``
  Finds parts and assemblies in the catalog whose name, description or source
  matches a natural-language query, by running ``pc search``; then presents the
  matches and, if you pick one, inspects or renders it. The reason to reach for
  it first is that the public repository already has the fastener, the bearing
  or the motor, and a part that is reused is a part nobody has to validate.

``/pc:describe``
  Writes a narratable, accessibility-oriented description of an existing object
  and stores it in the object's ``summary:``, where ``pc ide view`` and the
  Explorer show it. It does not guess from the name: it measures the bounding
  box and the volume, renders three views, renders a dimensioned drawing where
  one is available, and writes the description from those.


Producing files
===============

``/pc:render``
  Draws an object as a PNG, JPEG, SVG or DXF. It handles both cases -- ``pc
  render`` for an object a package declares, ``pc adhoc render`` for a file that
  belongs to no package -- and that distinction is the first thing it works out.

  What it adds over the bare command is the judgement: which angle answers the
  question (front, top, iso, or an arbitrary direction), rendering several
  angles at once when one will not do, drawing the ports and interfaces on top
  when the question is about how something connects, and rendering part of an
  assembly when the whole of it would be unreadable.

``/pc:export``
  Writes a CAD file out of an object a package declares -- STEP, BREP, STL, 3MF,
  OBJ, IGES, glTF, three.js, URDF, or a file type the package implements itself
  -- and **changes nothing in** ``partcad.yaml``. It can export part of an
  assembly rather than all of it. Use it to hand something to somebody else.

``/pc:convert``
  Changes what something *is*, which is the difference from exporting. For an
  object in a package it rewrites the declaration to point at the new file, so
  the package now says the object is a STEP where it used to say it was a
  script. For a bare file it converts the file and touches no package.


Checking and analysing
======================

``/pc:validate``
  The skill for the :doc:`Validation phase </digital_thread/lifecycle/validation>`,
  and the only one that judges a requirement no program can measure.

  It reads what the object's ``requirements:`` section asks for, runs ``pc test``
  for the ports, interfaces and physical properties PartCAD measures, runs every
  simulation and every engineering analysis scenario, renders the object from
  every angle that matters with its ports and interfaces drawn, and -- for an
  assembly -- reads the bill of materials and the assembly instructions. Then it
  gives every requirement a verdict: **met, not met, or "cannot tell"**, with
  the evidence named for each. The third verdict is what keeps it honest; a
  feature it has no evidence for is reported as unjudged rather than passed.

``/pc:sim-assembly-fea``
  Turns what a simulation measured into a stress analysis of one part, which is
  a thing neither tool does on its own.

  It runs the assembly's ``simulate:`` entry, reads the forces and moments acting
  at the end of the run on the body the part is welded into, works out which of
  them actually load that part and where they land, and writes a new named
  scenario into the part's ``fea:`` section beside any already there. Then it
  runs ``pc cae fea`` on it and shows the result where there is somewhere to
  show it. The step that matters is the third: a force on a welded body is not a
  force on the part until somebody decides which of it the part carries.
