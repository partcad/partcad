.. _dt-manufacturing-assembly:

########
Assembly
########

**Assembly** is the assembly instruction book: a page per step, drawn, to read
here or save. It is for an assembly, and it is what
:doc:`Build </digital_thread/lifecycle/manufacturing_build>` lists the steps of
-- the same steps, in the same order, as a document.

The book is written from the assembly itself. Each link of the ASSY file says
what it is joined to and how -- pushed, snapped or screwed in -- so the step
that adds it can be written out for a person to follow, with the two parts drawn
pulled apart by the ``exploded:`` gap of the connection. Nothing about the book
is declared separately from the assembly, which is why it cannot fall out of
step with it.

In the UI
=========

The document, as **PDF** or **HTML**, with **Recursive** and **Build parts** --
which are ``pc instructions -r -b`` -- and **Save…**.

.. image:: /images/dt-manufacturing-assembly.png
  :width: 100%
  :align: center
  :alt: The Manufacturing group's Assembly tab: the assembly instruction book, page by page

Manufacturing is for a part or an assembly; for a scene, a sketch or an
interface the whole group is disabled, and this tab is for an assembly alone.

On the command line
===================

.. code-block:: shell

  pc ide view --manufacturing-assembly :robot       # the tab itself
  pc instructions robot                             # robot.pdf, this assembly's own steps
  pc instructions -t html -r -b -O docs/ robot      # every step, every built part, as HTML
  pc render -t pdf robot                            # the same book as a rendered file

``-r`` puts in the steps of every sub-assembly that is built, each just before
the step that adds it, and ``-b`` how to make every part that is built, each
just before the step that first needs it. Both read the
:doc:`Build vs Buy </digital_thread/lifecycle/manufacturing_bvb>` choices made
on this machine.

How the steps are decided
=========================

See :ref:`how an assembly is manufactured <assembly-manufacturing>` and
:doc:`/assy` for what each ``connect:`` says about the joining -- the mating,
the ``how:``, the torque and the thread -- and
:doc:`/digital_thread/lifecycle/testing` for the ``connect`` check, which is
what reports a step the declaration says nothing about.

Agent skills
============

``/pc:validate``
  Reads the assembly instructions as part of giving a requirement its verdict.
