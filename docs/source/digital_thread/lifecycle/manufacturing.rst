Manufacturing
#############

.. toctree::
   :maxdepth: 2
   :hidden:

   manufacturing_bvb.rst
   manufacturing_build.rst
   manufacturing_buy.rst
   manufacturing_bom.rst
   manufacturing_assembly.rst


Manufacturing is how the object comes to exist: which of its parts are bought and
which are made, how each made part is made and from what, what the machines that
make it are told, and in what order it all goes together. PartCAD keeps that in
the same declaration as the design, so the part that is ordered is the part that
was analysed, and the instructions are written from the assembly they put
together.

What PartCAD captures
=====================

Whether it is made at all
-------------------------

``manufacturable:`` says whether an object is something anybody is going to
make or buy -- on the object, or for a whole package. A model of something
somebody else makes, an import kept as it arrived, a scene: these are records,
and say ``manufacturable: false``. Everything else is held to what follows.

Bought
------

A part or an assembly that is bought names who sells it, by ``vendor:`` and
``sku:``, and suppliers that carry it are found and asked for quotes by ``pc
supply``. An assembly that is sold assembled is ordered as one item, and nothing
inside it is looked at. See :ref:`procurement`.

Made
----

A part that is made says how, in a ``manufacturing:`` section: the method
(``additive``, ``subtractive``, ``forming``, ``sheet_metal``), the stock it is
made from (``source:``), the machines it is cut on (``cnc:``, ``laser:``,
``drill:``, ``cut:``) and what they are told, and the tolerance it is made to.
See :ref:`made-from-stock`, :ref:`subtractive` and :ref:`sheet-metal`. What it is
made of is its :ref:`material <materials>`; the firmware a board is flashed with
is its :ref:`software <software>`.

Put together
------------

An assembly is put together by following its own Assembly YAML file: each link
says what it is joined to and how -- pushed, snapped or screwed in -- so the steps
can be written out for a person to follow (see
:ref:`how an assembly is manufactured <assembly-manufacturing>` and :doc:`/assy`).

In the UI
=========

**Manufacturing** has five tabs, for a part or an assembly; for a scene, a
sketch or an interface the whole group is disabled. They are in the order they
are decided, and the first decides the rest. Each has a chapter of its own:

:doc:`Build vs Buy </digital_thread/lifecycle/manufacturing_bvb>`
  Everything the object is made of, and on each a switch: build it, or buy it.
  The one decision in the Digital Thread that is kept on the machine of whoever
  made it rather than in the package -- and the one that decides the other four
  tabs.

:doc:`Build </digital_thread/lifecycle/manufacturing_build>`
  What is built, in the order it is built in, each step a page of the
  instructions -- with the machine route drawn where a part declares one.

:doc:`Buy </digital_thread/lifecycle/manufacturing_buy>`
  What is bought: where each line can be obtained, and a quote per supplier.

:doc:`Bill of Materials </digital_thread/lifecycle/manufacturing_bom>`
  What has to be procured in order to have it, counted -- a made part as the
  stock it is cut from.

:doc:`Assembly </digital_thread/lifecycle/manufacturing_assembly>`
  The assembly instruction book, page by page, to read or save.

.. image:: /images/dt-manufacturing.png
  :width: 100%
  :align: center
  :alt: The Manufacturing group: its five tabs, open on Build vs Buy


On the command line
===================

- ``pc bom`` lists everything the object takes, with how many of each.
- ``pc supply find``, ``quote`` and ``order`` find suppliers, ask them for prices
  and order from them -- see :ref:`providers and suppliers <supply-chain>`.
- ``pc instructions`` writes the assembly instructions: a page per step, each
  drawn. It reads the **Build vs Buy** choices made on this machine, which is
  what makes it write the steps for what *you* are building rather than for
  everything the package could build.
- ``pc cam`` writes the programs the machines cut a part with -- see
  :ref:`machine routes <cam-routes>` for what it produces and what it cannot,
  and :ref:`pc cam <cam>` for the command.
- ``pc info`` reports the material, the stock and the tolerances an object
  resolved to, which is where a surprising bill of materials line is explained.

How manufacturing is checked
============================

``pc test`` asks of every manufacturable object what ``pc supply`` would order
and what ``pc instructions`` would tell somebody to do: the
``manufacturability`` check, and one for each method -- additive, subtractive,
forming, sheet metal, and the laser, drill and cut machines -- plus ``cam``,
whether the route a machine is to cut it with can be produced. See
:doc:`/digital_thread/lifecycle/testing`.

Agent skills
============
``/pc:validate``
  Reads the bill of materials and the assembly instructions as part of giving a
  requirement its verdict, which is the one skill that exercises this phase end
  to end.

``/pc:export`` and ``/pc:convert``
  Write the file a supplier or a machine is given, in the format it asks for.

Choosing what to build and what to buy is deliberately not something a skill
does: it is a decision about who has which machines, it is kept on the machine of
whoever made it rather than in the package, and it is the one input to this phase
that is nobody else's to guess.
