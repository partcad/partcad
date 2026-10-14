.. _digital-thread:

Digital Thread
##############

A *digital thread* is the one record of a product that every phase of its life
reads from and adds to: what it was asked to be, how it was designed, what
analysing it said, how it is made or bought, whether what was made is what was
asked for -- and, once it exists, how it is doing. A *digital twin* is that
record kept true to one physical thing for as long as the thing lasts. The
thread is what the twin is made of.

PartCAD is designed to be that record for manufacturable physical products, from
the first sentence about an idea to the order for the parts. This section
explains how, and how the typical workflows use it; the chapters after it take
one phase each.

How PartCAD holds the whole lifecycle
=====================================

Everything is a declaration in a package
----------------------------------------

There is no database and no export step between the phases. A product is a
:ref:`package <packages>` -- a ``partcad.yaml`` and the files beside it, kept in
git like source code -- and each phase of its life is a section of the
declaration of the same object:

.. list-table::
   :header-rows: 1
   :widths: 16 40 26 18

   * - Phase
     - What the object declares
     - What answers questions about it
     - In the Digital Thread
   * - :doc:`Requirements <requirements>`
     - ``requirements:`` -- features, ports, interfaces, physical properties
     - ``pc test``, ``/pc:validate``
     - **Requirements**
   * - :doc:`Design <design>`
     - the part's script or file, its parameters, ports and interfaces; an
       assembly's links and connections; sketches, scenes
     - ``pc info``, ``pc render``, ``pc export``
     - **Design**
   * - :doc:`Analysis <analysis>`
     - ``physics:``, materials, ``fea:``, ``dynamic:``, ``thermal:``, ``cfd:``,
       ``simulate:``
     - ``pc info``, ``pc cae``, ``pc sim``
     - **Analysis**
   * - :doc:`Manufacturing <manufacturing>`
     - ``manufacturing:``, ``vendor:`` and ``sku:``, materials, tolerances,
       software, an assembly's instructions
     - ``pc bom``, ``pc supply``, ``pc instructions``, ``pc cam``
     - **Manufacturing**
   * - :doc:`Validation <validation>`
     - the claims all of the above make, checked
     - ``pc test``, ``pc sim``, ``/pc:validate``
     - **Validation**

Because every phase is written into one declaration, nothing is copied from one
phase to the next, and nothing can fall out of step: the mass a requirement is
checked against is the mass ``pc info`` reports, worked out from the same solid
and the same material the bill of materials orders; the bracket the instructions
tell somebody to bolt on is the bracket that was analysed. Changing the design is
changing the one record, and every answer that depended on it is asked again.

One thing is deliberately left out of the package: which of the things that can
be either built or bought a particular person chooses to build (**Build vs Buy**).
The package says what can be bought and how what can be made is made; the choice
between them is a decision about who has which machines, and is kept on the
machine of whoever made it. A checkout does not carry it, so the build plan and
the order that follow from it can differ from one person to the next while the
product they describe does not.

Every answer is computed, not stored
------------------------------------

What PartCAD says about an object -- a picture, a mass, a bill of materials, a
verdict -- is worked out from the declaration when it is asked for, and cached
under a key made of everything the answer depends on (see
:ref:`caching`). A cached answer is never stale: change what it depends on and
the key changes with it. That is what lets one record serve every phase without
anybody having to remember to regenerate anything.

Every claim can be checked
--------------------------

A declaration states claims: this part is made by laser cutting, this assembly's
parts do not overlap, this mass is under 50 grams, this robot does not tip over.
``pc test`` checks every claim that can be measured, ``pc sim`` every claim about
behaviour that a simulation can show, and the ``/pc:validate`` agent skill
judges the rest from evidence it gathers and names. See :doc:`validation`.

Packages build on packages
--------------------------

A package imports others -- standard fasteners, a supplier's catalogue, a
colleague's sub-assembly -- and uses their objects by name (``//pub/std/...``).
The thread of a product runs through every package it is made of: the screw's
interface is the screw package's, its supplier is the supplier's, and both are
read where they are declared rather than copied in.

The lifecycle
=============

The phases are an order of questions rather than an order of work: each is
asked of the same object, and asked again whenever anything it depends on
changes.

#. **Requirements.** What the object has to be and do, from the point of view of
   whoever asked for it, written before the design is.
#. **Design.** What the object is: its geometry, how it is parameterised, how it
   connects to other objects.
#. **Analysis.** What engineering says about it: what it weighs, how it carries a
   load, how it behaves once the world is switched on.
#. **Manufacturing.** How it comes to exist: what is bought and what is built,
   how each part is made and from what, in what order it is put together.
#. **Validation.** Whether the object meets what was asked of it, and whether
   every claim the declaration makes holds.
#. **Operations.** How the thing that was made is doing. The Digital Thread
   reserves a tab for it; nothing is collected yet.

The Digital Thread panel of the :ref:`PartCAD IDE <partcad-ide>` and of the
:ref:`Visual Studio Code extension <vscode-extension>` is this list, as a strip
of tabs over whichever object is selected: **Requirements** (for an object that
declares any), **Design**, **Analysis**, **Manufacturing**, **Validation** and
**Operations**.

Typical workflows
=================

From an idea to a part
----------------------

#. Describe the part to an agent: ``/pc:gen-part`` (or ``/pc:gen-assembly``)
   writes the ``requirements:`` down from the description first, in its own
   terms, and only then models it (see :ref:`claude-plugin`).
#. ``pc test`` proves it builds, can be made, and has the ports, interfaces and
   physical properties it is required to have.
#. ``/pc:validate`` runs everything, looks at the part from every angle that
   matters, and gives each requirement a verdict -- met, not met, or "cannot
   tell", with the evidence named.

Changing a design without breaking it
-------------------------------------

#. Edit the script or the declaration; the Digital Thread shows the object again
   as soon as it is saved.
#. Open **Validation**: every check runs again, through the cache, so what did
   not change is not asked again. A failure says what it found; an interference
   leaves an assembly of the two parts and what they share to look at.
#. ``pc test`` and ``pc sim`` in CI hold every change to the same checks, and
   rendered pictures checked in beside the package make a change in how anything
   looks a diff somebody reviews.

From a design to an order
-------------------------

#. **Manufacturing → Build vs Buy** decides, per part and sub-assembly, what is
   made and what is ordered; the choice is kept on the machine of whoever made
   it.
#. ``pc bom`` lists what that takes, ``pc supply quote`` asks suppliers for it,
   and ``pc supply order`` orders it.
#. ``pc instructions`` writes the book that puts it together, step by step, and
   ``pc cam`` the programs the machines cut its parts with.

Reviewing somebody else's product
---------------------------------

``pc test -P <package>...`` checks every object of a package and everything below
it. In the Digital Thread, each object shows its requirements, its design, its
analyses, how it is made, and its checks with what each one found -- the whole
thread of one object on one screen.

.. toctree::
   :maxdepth: 2

   requirements.rst
   design.rst
   analysis.rst
   manufacturing.rst
   validation.rst
