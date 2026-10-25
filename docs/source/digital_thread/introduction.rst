############
Introduction
############

A *digital thread* is the one record of a product that every phase of its life
reads from and adds to: what it was asked to be, how it was designed, what
analysing it said, how it is made or bought, whether what was made is what was
asked for -- and, once it exists, how it is doing. A *digital twin* is that
record kept true to one physical thing for as long as the thing lasts. The
thread is what the twin is made of.

PartCAD is designed to be that record for manufacturable physical products, from
the first sentence about an idea to the order for the parts. This chapter explains how; :doc:`/digital_thread/lifecycle` takes the phases one at a time, and
:doc:`/digital_thread/workflows/index` the work that runs through them.


Everything is a declaration in a package
========================================

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
   * - :doc:`Requirements </digital_thread/workflows/requirements>`
     - ``requirements:`` -- features, ports, interfaces, physical properties
     - ``pc test``, ``/pc:validate``
     - **Requirements**
   * - :doc:`Design </digital_thread/workflows/design>`
     - the part's script or file, its parameters, ports and interfaces; an
       assembly's links and connections; sketches, scenes
     - ``pc info``, ``pc render``, ``pc export``
     - **Design**
   * - :doc:`Analysis </digital_thread/workflows/analysis>`
     - ``physics:``, materials, ``fea:``, ``dynamic:``, ``thermal:``, ``cfd:``,
       ``simulate:``
     - ``pc info``, ``pc cae``, ``pc sim``
     - **Analysis**
   * - :doc:`Manufacturing </digital_thread/workflows/manufacturing>`
     - ``manufacturing:``, ``vendor:`` and ``sku:``, materials, tolerances,
       software, an assembly's instructions
     - ``pc bom``, ``pc supply``, ``pc instructions``, ``pc cam``
     - **Manufacturing**
   * - :doc:`Validation </digital_thread/workflows/validation>`
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
====================================

What PartCAD says about an object -- a picture, a mass, a bill of materials, a
verdict -- is worked out from the declaration when it is asked for, and cached
under a key made of everything the answer depends on (see
:ref:`caching`). A cached answer is never stale: change what it depends on and
the key changes with it. That is what lets one record serve every phase without
anybody having to remember to regenerate anything.

Every claim can be checked
==========================

A declaration states claims: this part is made by laser cutting, this assembly's
parts do not overlap, this mass is under 50 grams, this robot does not tip over.
``pc test`` checks every claim that can be measured, ``pc sim`` every claim about
behaviour that a simulation can show, and the ``/pc:validate`` agent skill
judges the rest from evidence it gathers and names. See :doc:`/digital_thread/workflows/validation`.

Packages build on packages
==========================

A package imports others -- standard fasteners, a supplier's catalogue, a
colleague's sub-assembly -- and uses their objects by name (``//pub/std/...``).
The thread of a product runs through every package it is made of: the screw's
interface is the screw package's, its supplier is the supplier's, and both are
read where they are declared rather than copied in.
