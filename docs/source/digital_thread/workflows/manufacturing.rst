Manufacturing
#############

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

Working on manufacturing
========================

- ``pc bom`` lists everything the object takes, with how many of each.
- ``pc supply find``, ``quote`` and ``order`` find suppliers, ask them for prices
  and order from them.
- ``pc instructions`` writes the assembly instructions: a page per step, each
  drawn.
- ``pc cam`` writes the programs the machines cut a part with (see :ref:`cam`).

In the Digital Thread
=====================

**Manufacturing** has five tabs, for a part or an assembly:

- **Build vs Buy**: everything the object is made of, and for each a switch --
  build it, or buy it. The choice is kept on the machine of whoever makes it, and
  decides the other tabs.
- **Build**: what is built, in the order it is built in, each step a page of the
  instructions.
- **Buy**: what is bought, from whom, and for how much.
- **Bill of Materials**: everything it takes, counted.
- **Assembly**: the assembly instructions, page by page, to read or save.

How manufacturing is checked
============================

``pc test`` asks of every manufacturable object what ``pc supply`` would order
and what ``pc instructions`` would tell somebody to do: the
``manufacturability`` check, and one for each method -- additive, subtractive,
forming, sheet metal, and the laser, drill and cut machines -- plus ``cam``,
whether the route a machine is to cut it with can be produced. See
:doc:`/digital_thread/workflows/testing`.


.. toctree::
   :maxdepth: 2

   cam.rst
   supply_chain.rst
