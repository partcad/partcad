Operations
##########

Operations is the phase after the object is written: what has become of it
since. Two questions are answered so far, both about the record rather than
about a made item -- **how it got to be what it is**, revision by revision, and
**what depends on it**. The phase's other half, a *digital twin* kept true to one
physical object with its serial number, collects nothing yet.

In the UI
=========

**Operations** is the last of the groups in the Digital Thread's tab strip, and
it has a strip of its own: **Revisions** and **Used By**. It is there for every
object whose package PartCAD knows -- a part, an assembly, a scene, a sketch, an
interface, and a package itself.

Not every kind of object has every group. An interface is ports rather than a
shape, so it has **Design** -- its 3D view, with no strip under it -- and
**Operations**. A sketch is flat: **Requirements** when it declares any,
**Design** with **2D** and **Draft** (a drawing of its one plane rather than the
three planes and the perspective of a solid), and **Operations**. A package,
selected in the Package Explorer, has **Requirements** -- its own (see
:ref:`requirements`) -- and **Operations**.

Revisions
---------

The commits that changed the object's package, newest first, down the left, each
as the first eight characters of its id; the one checked out is marked. A package
that shares its repository with others lists the commits that changed *its*
directory. A package in no git repository, or one nothing of which was ever
committed, has no history, and the tab says **This package is not published
yet**.

Selecting a revision loads the package at it, beside what is checked out (see
:ref:`package-revisions`), and compares the two side by side: the revision on the
left, the object as it is now on the right, a line changed, removed or added in
the colours the editor's own diff uses. Both sides are the object written out as
``pc copy`` writes one -- rendered, normalized, defaults left out -- so what
differs is what the object *means*; a comment or a reformatted line is no
difference. A package is compared by its ``partcad.yaml`` as Jinja2 rendered it
when PartCAD read it: the very text PartCAD parsed.

Along the bottom, the Simulation tab's folded views: **Uses (Dependencies)**, the
packages the package declares as its dependencies at that revision, each with the
commit it is at -- click the dependency, or its commit, to open it in the Package
Explorer -- and **Used By**, the objects PartCAD has loaded that refer to the
package at that revision, each with how many times (an assembly placing a bolt
four times uses it four times), each opening the object. Each is asked for the
first time it is opened.

Used By
-------

The objects PartCAD has loaded that refer to the one on screen -- or, for a
package, to anything in it -- each with how many times, each opening the object.
Only what is loaded is looked at, and the tab says so: what PartCAD has not read
yet cannot be said to use anything, and an assembly not built yet is counted by
what its declaration names.

On the command line
===================

There is no command that lists a history -- ``git log`` does that -- but every
part of the tab is reachable from one:

.. code-block:: shell

  pc info //@v1.2:bracket                       # an object at a revision
  pc copy //@v1.2:bracket bracket_v1            # brought back under a name of its own
  pc copy --dry-run bracket x                   # the text the tab compares
  pc ide view --operations-revisions :bracket   # this tab
  pc ide view --operations-used-by :bracket

Agent skills
============

None of its own. An agent reaches the same answers through the MCP server's
``execute``, which calls the daemon methods the tab is drawn from:
``revisions.list``, ``revisions.compare``, ``revisions.uses``,
``revisions.used_by`` and ``usage.used_by``.

What is not here yet
====================

A digital twin needs one record per object, every answer computed from it rather
than stored beside it, and a pin on every dependency, so that the design a made
item was made from can be checked out again exactly as it was (see
:doc:`/digital_thread/change_management`) -- which is what the Revisions tab
reads. What it does not have yet is anything about the made items themselves:
no section of a ``partcad.yaml`` records an individual made item. Until there is,
the way to keep track of what was made is :doc:`Manufacturing
</digital_thread/lifecycle/manufacturing>` together with git: the commit a build
was made from is the record of what was built.
