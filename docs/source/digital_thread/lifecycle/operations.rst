Operations
##########

Operations is the phase after the product exists: how the thing that was made is
actually doing. It is the phase that turns a digital thread into a *digital
twin* -- a record kept true to one physical object, with its serial number, for
as long as that object lasts.

**Nothing is collected yet.** This page is here because the phase is part of the
lifecycle and because the Digital Thread reserves its place, not because there
is a feature to describe.

In the UI
=========

**Operations** is the last of the five groups in the Digital Thread's tab strip,
and it is the one group that is always shown **disabled** -- for every object,
whatever it declares. It has no strip of its own, so this phase has no sub-tabs
and there is nothing to picture: every screenshot of the panel on these pages
shows it, greyed, at the end of the row. Hovering over it says why.

**Process Emulation**, the third tab of :doc:`Validation
</digital_thread/lifecycle/validation>`, is reserved in the same way and for the
related question of how making it would go. It holds nothing yet either.

On the command line
===================

Nothing. No section of a ``partcad.yaml`` records anything about an individual
made item, and no ``pc`` command reads or writes one: a package describes a
*type* of thing -- what to make, and how -- and says nothing about the instances
that were made from it. ``pc ide view`` has a flag for every tab of the other
four groups and none for this one.

Agent skills
============

None. A skill is a procedure for working on a package, and this phase has
nothing in a package to work on. ``/pc:validate`` is the nearest thing: it
judges whether what was designed meets what was asked for, which is the question
this phase would ask again of the thing that was actually made.

What is already in place
========================

What the other phases already give this one is the part that is hard: one record
per object, every answer computed from it rather than stored beside it, and a
pin on every dependency, so that the design a made item was made from can be
checked out again exactly as it was (see :doc:`/digital_thread/change_management`).
A twin needs that before it needs telemetry.

Until there is something here, the way to keep track of what was made is
:doc:`Manufacturing </digital_thread/lifecycle/manufacturing>` -- the bill of
materials, what was ordered and from whom, and the instructions somebody
followed -- together with git: the commit a build was made from is the record of
what was built.
