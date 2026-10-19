Managing changes in large projects
##################################

A product of any size soon depends on packages of its own: a library of the company's standard parts, the
interfaces its products share, the assemblies one team builds and another uses. Those packages change, and a
change to one is a change to everything built from it. This page is about making those changes on purpose.

None of it is new. It is how the public index, `partcad-index <https://github.com/partcad/partcad-index>`_, is run
-- a package of packages that every package ``pc init`` creates depends on -- and the rules that keep it working are
the rules that keep a library of your own working. They are repeated here for that library, and the index's
`CONTRIBUTING.md <https://github.com/partcad/partcad-index/blob/devel/CONTRIBUTING.md>`_ is the same advice as the
public index applies it.

.. _change-rules:

=========
The rules
=========

#. **Pin every dependency to a particular revision**, with or without ``track:``.
#. **Say which PartCAD every package needs**, with ``partcad:``.
#. **Merge every change to** ``devel``. Nothing merges to ``main``.
#. **Move** ``main`` **only by fast-forward from** ``devel``. That is the release.
#. **Treat a branch somebody tracks as a promise.** It keeps working for everybody it worked for when they started
   tracking it; a breaking change goes to a new branch.
#. **Have a library's index pin an exact commit of every package in it.**

The sections below say what each one is for.

====================
Pin every dependency
====================

A ``git`` dependency says which branch it follows with ``track:`` and which commit of it the package is built
against with ``revision:`` (see :ref:`pinning-dependencies`):

.. code-block:: yaml

  dependencies:
    std:
      type: git
      url: git@github.com:example/partcad-std.git
      track: main
      revision: 5e2161123918f9c796c44e190f5a2e8d5ee7292e

``pc add dep`` and ``pc init`` write it that way, and loading a package never moves it. ``pc update`` does,
when you ask: it moves every ``revision:`` to the tip of its ``track:`` and leaves the change in
``partcad.yaml`` for you to review and commit. So:

* every checkout of a commit builds against the same commits of everything it depends on, today and in a year;
* what changed between two builds is in the history of your own repository, as a diff of ``revision:`` lines;
* taking a dependency's new commits is a change you make, in a commit of its own, and can revert.

Run ``pc update`` as a change of its own and review what moved, the way a dependency bot's pull request is
reviewed -- on a schedule, if you want one. Do not use ``forceUpdate`` (``--force-update``) to keep up to date:
it follows ``track:`` past the pin without writing anything down, which is right for trying out what a
dependency is about to release and wrong for anything you will need to reproduce.

A dependency of the ``local`` type, and every sub-directory of a package that holds a ``partcad.yaml``, needs no
pin: it is in the same repository, so the commit you check out *is* its pin. Packages that always change together
belong in one repository for that reason -- a change and every package it affects then land in one commit, and
there is nothing to coordinate.

=================================
Say which PartCAD a package needs
=================================

``partcad:`` in a package's ``partcad.yaml`` is the oldest PartCAD it works with:

.. code-block:: yaml

  partcad: ">=0.8.175"

A PartCAD older than that refuses the package with ``Incompatible PartCAD version!`` rather than loading it and
getting it wrong. That matters more than it sounds: PartCAD gives a field a new meaning from time to time, and an
older PartCAD reading a package written for the newer meaning does not fail -- it computes something else. The
public index's fluids are an example: their densities are in kg/m³, and the PartCAD before the one they require
would have read the same numbers in g/mm³ and made water a million times too dense.

``pc init`` writes the version that ran it, which is correct and usually higher than it needs to be. Keep it as
low as is true: every release you exclude is a user you make upgrade. Raise it when the package starts using
something a newer PartCAD added -- or use the new form only where it is available, and keep the old one for the
rest (see :ref:`serving-two-partcads`).

Pin the PartCAD your CI runs as well, the way you pin anything else it installs, and upgrade it in a change of its
own. Upgrade PartCAD first and raise ``partcad:`` after, never the other way round.

========================
Branches: devel and main
========================

Give every package repository two long-lived branches:

``devel``
  What every change is merged to, after review and CI. It is the newest state, and it may be ahead of what
  anybody depends on.

``main``
  What other packages track. It moves only by fast-forward to a commit of ``devel`` that has been tested --
  never by a merge of its own, and never by a commit made on it:

  .. code-block:: shell

    git fetch origin
    git push origin <tested commit of devel>:refs/heads/main   # refused unless it is a fast-forward

So ``main`` is always a commit that ``devel`` has had, and a consumer's ``pc update`` takes a release, never
work in progress. Make ``devel`` the default branch and protect ``main`` so that nothing merges to it.

PartCAD and the public index are both run this way. To try your packages against what the index is about to
release, ``--devel-index`` (``PC_DEVEL_INDEX=true``) makes any command use the index's ``devel`` instead of its
``main``.

=============================
A tracked branch is a promise
=============================

Once another package tracks a branch of yours, every commit you push to it reaches that package at its next
``pc update``. The branch therefore has to keep working for everybody it worked for when they started tracking
it:

* with every PartCAD release it supported then -- a commit to it must not raise ``partcad:``;
* with every package that uses it: every part, assembly, sketch, interface, port, parameter and sub-package
  stays, under the same name, with the same units, defaults and placement.

Anything new goes beside what is there. Mark what is being replaced as deprecated in its ``desc:``, and remove it
on a new branch, later.

The public index states this exactly: a branch it tracks keeps supporting every PartCAD release since the one the
package's own ``partcad:`` required when the index started tracking that branch. Hold the packages of a library
of your own to the same.

========================
Making a breaking change
========================

A breaking change is one after which something that used the package stops working or comes out different:
removing or renaming an object, a port or a parameter; changing a parameter's meaning, units or default; moving a
port, so that what is mated to it moves; requiring a newer PartCAD.

#. **Avoid it if you can.** Add the new beside the old, and nothing breaks.
#. **Make it on a new branch** -- ``v2``, or ``partcad-0.8.210`` after the PartCAD it needs -- and declare that
   PartCAD in ``partcad:``.
#. **Leave the old branch as it is.** Never force-push, rebase or delete a branch that is or was tracked: the
   commits other packages pinned have to stay fetchable, for as long as anyone may check out a commit that names
   them.
#. **Move each consumer deliberately**, in a change of its own: switch its ``track:`` to the new branch, run
   ``pc update``, and fix what the new branch broke, in the same commit.
#. **Release in order.** A package may require a PartCAD only once that PartCAD is released, and a consumer may
   move to a package only once the package's new branch is ready. When a change spans several of your
   packages, release the one depended on first, then the ones that depend on it.

When the same change has to reach many consumers, make it in three releases rather than one -- the way PartCAD
changes what a package may say (see :ref:`release-process`): first add the new form beside the old one and
release that; then move every consumer to the new form, each at its own pace; then remove the old form, on a new
branch, once nothing pinned uses it.

=======================================
An internal index for a package library
=======================================

A library of more than a few packages is easiest to consume the way the public index is consumed: one repository
whose ``partcad.yaml`` files are a tree of dependencies on the library's packages, each one pinned. A product then
depends on the library once:

.. code-block:: yaml

  dependencies:
    lib:
      type: git
      url: git@github.com:example/partcad-library-index.git
      track: main
      revision: 2b2cc80c285d94e8f99b50349d1c9d30b92ca115

and refers to everything in it by path, ``//lib/fasteners/m3:screw``, however the library's repositories are
split up or moved.

Run that repository as the public index is run:

* **Every** ``git`` **dependency in it pins an exact commit**, under the ``track:`` of the branch it follows. What a
  product gets from the library changes only when a change to the index changes a ``revision:``.
* **Every package in it declares** ``partcad:``.
* **Changes merge to its** ``devel``, **and its** ``main`` **moves only by fast-forward** from ``devel``, once
  ``devel`` has been tested with the products that use it.
* **Pins move in reviewed changes.** ``pc update`` in a checkout of the index moves every tracked dependency to
  the tip of its branch at once; the diff is the list of packages that changed, to review before it is merged.
* **A package's breaking change switches its** ``track:`` **to a new branch**, in a change to the index that
  also fixes every package of the library that used what broke.

Products ``pc update`` to take a release of the library, and every product can be on a different one.
