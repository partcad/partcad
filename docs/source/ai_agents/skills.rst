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

==============
What there is
==============

**Setting up**

``/pc:setup``
  Puts ``pc`` on this machine -- the standalone build, or the wheel into the active Python environment -- and,
  when the agent runs inside Visual Studio Code or VSCodium, the PartCAD extension into that editor.

``/pc:init``
  Creates a package in the current directory, by running ``pc init``.

**Generating geometry**

``/pc:gen``
  Decides whether the request is a part, an assembly or a 2D sketch, and follows the matching skill below.

``/pc:gen-part``
  Writes down what the part is required to be, authors the CAD script, and validates it by rendering several
  views and checking each against the description. A single projection hides whatever is behind it, which is
  why it is several.

``/pc:gen-assembly``
  Reuses or generates the component parts, authors the ``.assy`` -- explicit placement, or interface mates --
  and validates the result the same way.

``/pc:gen-sketch``
  Authors a 2D sketch (build123d, CadQuery, DXF, SVG or basic) and validates it by rendering to SVG.

``/pc:add-interfaces``
  Adds ``interfaces``, ports and ``implements:`` to an existing part, so PartCAD can mate it by connection
  rather than by hand-written coordinates. It works the port positions out of the geometry and proves them
  twice: by drawing them on the part, and by mating two instances in a throwaway assembly.

**Looking at what is there**

``/pc:search``
  Finds parts and assemblies in the catalog whose name, description or source matches a query.

``/pc:describe``
  Writes a narratable description of an existing object from its measured bounding box and its renders, and
  stores it in the object's ``summary:``.

**Producing files**

``/pc:render``
  Writes a 2D projection -- PNG, JPEG, SVG or DXF -- from one or many viewing angles, optionally with the
  connection ports and interfaces drawn on top.

``/pc:export``
  Writes a CAD file out of an object the package declares, changing nothing in ``partcad.yaml``.

``/pc:convert``
  Changes what something *is*: for an object in a package it rewrites the declaration to point at the new
  file; for a bare file it converts the file and touches no package.

**Checking and analysing**

``/pc:validate``
  Checks an object against the requirements its ``requirements:`` section declares, by running ``pc test``,
  and reports what each requirement found.

``/pc:sim-assembly-fea``
  Turns what a simulation of an assembly measured into a stress analysis of one part in it: runs the
  assembly's ``simulate:`` entry, reads the forces off the result, and drives ``pc cae fea`` with them.

==================
Writing your own
==================

The library lives in ``ai-agents/common/skills`` in the PartCAD repository, one directory per skill. A skill
is a ``SKILL.md`` with a name, a one-line description that decides when an agent reaches for it, and the
procedure. :doc:`/contributing` covers getting one into PartCAD; nothing stops you keeping one in your own
package's repository instead.
