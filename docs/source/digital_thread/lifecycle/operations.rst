Operations
##########

Operations is the phase after the object is written: what has become of it since. It is four questions, asked of
a *subject* -- a package, or one object of it -- at a *state* of its git repository: **Revisions** (how it got to
be what it is, and making the next one), **Dependencies** (what it is made of and from), **Used By** (what is made
of it) and **Impact** (what a change of it reaches). Each is a tab of the Digital Thread, ``pc ops`` commands and
MCP tools of the same name. The phase's other half, a *digital twin* kept true to one physical object with its
serial number, collects nothing yet.

A state is a revision -- a commit id, a tag, a branch, ``HEAD~1`` -- or ``STAGED``, what the git index holds and
a new revision would be made of, or ``WORKTREE``, the files on disk. It is written after ``@`` like any revision
(``//pub/examples@STAGED:bracket``; see :ref:`package-revisions`), so every command reaches it, and a comparison
takes two of them.

In the UI
=========

**Operations** is the last of the groups in the Digital Thread's tab strip, and it has a strip of its own:
**Revisions**, **Dependencies**, **Used By** and **Impact**. Every object whose package PartCAD knows has it -- a
part, an assembly, a scene, a sketch, an interface, and a package itself, selected in the Package Explorer. A
piece of software has Revisions and Used By; what it depends on is its own business.

Not every kind of object has every group. An interface is ports rather than a shape, so it has **Design** -- its
3D view, with no strip under it -- and **Operations**. A sketch is flat: **Requirements** when it declares any,
**Design** with **2D** and **Draft** (a drawing of its one plane rather than the three planes and the
perspective of a solid), and **Operations**. A package has **Requirements** -- its own (see
:ref:`requirements`) -- and **Operations**, which it opens on.

Revisions
---------

**A package lists every revision; an object lists only the revisions that changed it.** A package lists every
commit that changed its directory, newest first, a page at a time; a commit that changed nothing but packages in
directories below it says which. An object lists the commits in which its declaration or a file it is built from
changed, each marked with how: *added*, *removed*, *declaration*, *source*. Only direct changes: a change to
something the object uses is a revision of that other object, and what it did to this one is Impact's question.
A package in no git repository, or one nothing of which was ever committed, has no history, and the tab says
**This package is not published yet**.

Above the commits, two rows that are not commits, shown only when they differ from what is below them:

* **WORKTREE** -- the changes that are not staged, with **Stage all**, which stages every change of the subject:
  a package's own files, or an object's files and its own declaration in ``partcad.yaml`` -- only the lines of it,
  so that another object's edit in the same file stays out. Beside it, one sentence to hand an agent that is to
  stage something finer, with **Copy for your agent**.
* **STAGED** -- what a new revision would hold, with **New revision...**: a message (a first draft is written from
  what changed), and the checks a revision has to pass. Only what is staged is committed. Before it is, the tab
  says what else is staged -- other objects, other packages, files in no package -- and what of the subject is
  not, or changed again since it was staged, and asks before committing on those terms. Lint and the
  qualification tests of what is staged then run, unless **Skip lint and tests** is ticked. The author is who git
  says the user is on the machine the editor runs on.

Selecting a row shows the comparison side by side: **This change** (a commit against its parent, STAGED against
HEAD, WORKTREE against STAGED) or **Since then** (the row against the files on disk). Both sides are the object
written out as ``pc copy`` writes one -- rendered, normalized, defaults left out -- so what differs is what the
object *means*; a comment or a reformatted line is no difference. An object lists the files it is built from that
changed, which its declaration does not show. A package lists the objects that changed, each with how, and the
files that are no object's, above its ``partcad.yaml`` as Jinja2 rendered it at each. Along the
bottom, three folds about the subject at the selected row, each asked the first time it is opened:
**Dependencies at it**, **Used By at it**, and **Impact since it**.

Dependencies
------------

A package lists what it depends on, and changes it: the dependencies it declares, each with what its declaration
says -- the location, the branch it tracks, the commit it is pinned to -- and the commit it is at, each with
**Update** (its pin moved to the tip of its branch) and **Remove**; **Add dependency...**; the packages its
objects use without declaring them, through an index the workspace root imports, say, each with **Declare...**;
and its sub-packages, which need no pin, since the commit checked out is theirs. A ``partcad.yaml`` it writes is a
change of the working tree, which shows in the WORKTREE row of Revisions until it is made a revision.

An object lists what it names and, once built, what it places: each object with how (*placed*, *source (alias)*,
*source (enrich)*, *sketch*, *implements*, *inherits*, ...), how many times, and the commit of the package it
comes from, each opening the object.

Used By
-------

An object lists the objects PartCAD has loaded that use it, each with how and how many times (an assembly placing
a bolt four times uses it four times), each opening the object. A package also lists the packages that declare it
as a dependency, each with the revision it pins and how many revisions behind that is. Only what is loaded is
looked at, and the tab says so: what PartCAD has not read yet cannot be said to use anything, and an assembly not
built yet is counted by what its declaration names. **Load workspace** loads every package of the workspace
first.

Impact
------

**Impact says what a change reaches: the objects it changed, everything that uses them, and what each of those
now risks.** The change is one of: everything not committed (the default), what is staged, what is not staged, or
everything since a revision. Each object reached is one row, reached as *changed* or *via* the objects in between,
with findings:

* **breaking** -- an object removed or a parameter removed while something uses it, a reference that no longer
  resolves, a port removed while mated;
* **changed** -- a shape that moved (**Measure** says by how much: volume and mass, as ``pc compare`` reads
  them); what is reached through a change of prose alone has not moved;
* **verify** -- requirements and qualification tests to run again (**Test** runs them), drawings made from it now
  out of date;
* **info** -- nothing but prose changed.

An object also lists what it uses that changed. A package that pins this one to a git commit is listed apart: the
change does not reach it until it moves its pin. Impact looks where Used By looks. In the subject's repository,
what uses what is read at the state the change is made of -- in what is staged, a staged alias of a removed part
uses it, whatever the file on disk says now; a package of another repository is as it is loaded, has no earlier
state to measure its shape against, and is tested as it is.

On the command line
===================

Every view of the tab is a command, asking the daemon what the tab asks it:

.. code-block:: shell

  pc ops summary bracket                 # the views the bracket has, and a line from each
  pc ops rev list                        # every revision of this package
  pc ops rev list bracket                # only the revisions that changed the bracket
  pc ops rev diff --since v1.2 bracket   # what changed since v1.2, as a unified diff
  pc ops rev diff --staged               # what is staged, object by object
  pc ops rev status                      # what is staged and what is not
  pc ops rev stage bracket               # stage the bracket's files and its declaration
  pc ops rev new -m "Thicker flange"     # commit what is staged, once lint and the tests pass
  pc ops deps list                       # declared, used but not declared, sub-packages
  pc ops deps add std https://github.com/acme/std.git --track main
  pc ops deps update --all               # every tracked dependency to the tip of its branch
  pc ops used-by --load bracket          # what in this workspace uses the bracket
  pc ops impact --staged --load          # what the staged change reaches
  pc info //@v1.2:bracket                # an object at a revision
  pc copy //@v1.2:bracket bracket_v1     # brought back under a name of its own
  pc ide view --operations-impact :bracket

Where the tab draws a comparison side by side, ``pc ops rev diff`` prints it as a unified diff -- the same
comparison of the same two texts, written by the daemon (see ``pc ops`` in :doc:`/cli`). ``pc add dep`` and
``pc update`` are the old names of ``pc ops deps add`` and ``pc ops deps update --all``.

Agent skills
============

None of its own. An agent reaches the same answers through the MCP server (``pc mcp``), whose ``ops_summary``,
``ops_rev_list``, ``ops_rev_diff``, ``ops_rev_status``, ``ops_rev_stage``, ``ops_rev_new``, ``ops_deps_list``,
``ops_deps_add``, ``ops_deps_remove``, ``ops_deps_update``, ``ops_used_by`` and ``ops_impact`` tools are these
commands -- the diff unified as the command prints it -- and through ``execute``, which reaches the daemon methods
the tabs are drawn from: ``ops.views``, ``ops.rev.list``, ``ops.rev.diff``, ``ops.rev.status``,
``ops.rev.stage``, ``ops.rev.new``, ``ops.deps.list``, ``ops.deps.add``, ``ops.deps.remove``,
``ops.deps.update``, ``ops.used_by`` and ``ops.impact``. The tools that write ask the user first; ``ops_rev_new``
agrees to what else is staged, or to what is not, only once the user has.

What is not here yet
====================

A digital twin needs one record per object, every answer computed from it rather than stored beside it, and a pin
on every dependency, so that the design a made item was made from can be checked out again exactly as it was (see
:doc:`/digital_thread/change_management`) -- which is what the Revisions tab reads. What it does not have yet is
anything about the made items themselves: no section of a ``partcad.yaml`` records an individual made item. Until
there is, the way to keep track of what was made is :doc:`Manufacturing </digital_thread/lifecycle/manufacturing>`
together with git: the commit a build was made from is the record of what was built.
