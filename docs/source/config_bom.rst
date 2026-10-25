####################
Interchangeable BOM
####################

A bill of materials is usually a flat list of exact things to buy. PartCAD lets it be something more useful:
a list of what each position has to *be*, which a package can then satisfy with a particular product. The
same assembly can be quoted from two different suppliers, or built from what is in the drawer, without the
assembly changing.

This is the object-oriented part of PartCAD, and it is built out of three things that are documented
elsewhere in this section: :doc:`interfaces </config_geometry>`, which say how a part connects;
``alias``, which gives an existing part another name; and ``enrich``, which makes an opinionated version of
an existing part by fixing some of its parameters. Put together, they let a part be refined by steps, from
"something that bolts on here" to "this exact item from this exact vendor".

===========================
Abstract and concrete parts
===========================

A part declaration does not have to say where the part comes from. What makes a part usable in an assembly is
its geometry and its interfaces -- where it sits, and what it mates with. A part that has those and no
``vendor``/``sku`` is **abstract**: the assembly knows how it fits, and not yet which product it is.

A part that does name a ``vendor`` and an ``sku`` is **concrete**. It is a thing somebody sells, and
``pc supply`` can quote and order it (see :ref:`procurement`).

Between the two there is a chain, and each link narrows the choice:

.. code-block:: yaml

  # //pub/std/fastener: the abstract shape of the thing
  parts:
    m3-bolt:
      type: build123d
      path: bolt.py
      parameters:
        length: { type: float, default: 10 }
      implements:
        m3-thread: {}          # whatever this is, it mates like an M3 bolt

  # a package that has chosen a length but not a supplier
  parts:
    m3x16:
      type: enrich
      source: //pub/std/fastener:m3-bolt
      with:
        length: 16

  # a package that has chosen a product
  parts:
    m3x16-acme:
      type: enrich
      source: ../std:m3x16
      with: {}
      vendor: acme
      sku: BOLT-M3-16-A2

Each of those is a part in its own right, and each can be used in an assembly. ``alias`` does the same
without changing anything -- a local name for a part that lives somewhere else, so an assembly refers to
``:bolt`` and the package decides what that is.

=================================
Why the interface is what matters
=================================

An assembly that mates by :ref:`interfaces <interfaces>` rather than by coordinates does not name positions;
it names connections. So replacing one bolt with another bolt that implements the same interface does not
move anything: the mate is recomputed from the new part's ports. That is what makes a position in the bill of
materials interchangeable rather than merely editable.

It is also what makes the refinement chain above safe. An ``enrich`` of a part keeps the source's interfaces,
so a part narrowed three times still mates the way the abstract one did -- and ``pc test`` checks that it
does, since the connection test is run against whatever the assembly actually resolves to.

========================================
Assemblies can be either, and so can you
========================================

An assembly may name concrete parts, in which case its bill of materials is a list of products and
``pc supply`` can price it as it stands. Or it may name abstract ones, in which case it is a design that
somebody -- you, a downstream package, a customer -- completes by choosing products for its positions. A
package of your own that imports such an assembly and declares ``enrich``\ es for its abstract parts is how
that choice is written down, versioned and reviewed like everything else.

.. note::

  Making an assembly that still contains abstract parts *manufacturable* -- having PartCAD choose products
  for the open positions, or order against the interface rather than against an SKU -- is not implemented
  yet. Today an assembly is procured from the parts it actually resolves to, so the positions have to be
  concrete by the time you ask ``pc supply`` or ``pc bom`` for an answer.

See :doc:`/config_making` for how a concrete part is bought or made, and :doc:`/cli` for ``pc bom``, which
prints the list the assembly resolves to.
