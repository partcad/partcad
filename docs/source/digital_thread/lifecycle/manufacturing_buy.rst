.. _dt-manufacturing-buy:

###
Buy
###

**Buy** is what is bought: where each line can be obtained, and a quote per
supplier. It is the other half of
:doc:`Build vs Buy </digital_thread/lifecycle/manufacturing_bvb>` -- every line
whose switch says *buy* is asked about here.

In the UI
=========

A line per thing bought, and under each the suppliers that carry it with what
each one quoted. A line nobody carries says so, which is the same finding the
``manufacturability`` check reports from the command line.

.. image:: /images/dt-manufacturing-buy.png
  :width: 100%
  :align: center
  :alt: The Manufacturing group's Buy tab: what is bought, from whom, and for how much

On the command line
===================

.. code-block:: shell

  pc ide view --manufacturing-buy :robot    # the tab itself
  pc supply find :bolt                      # who carries it
  pc supply quote :bolt                     # what they want for it
  pc supply order :bolt                     # order it
  pc supply caps //vendor/store:myGarage    # what a provider can do

``find`` and ``quote`` take parts and assemblies alike. An assembly that is
sold assembled is ordered as one item, and the walk down stops at every
sub-assembly that is; ``-r`` walks all the way to the parts regardless.

.. _supply-chain:

Providers and suppliers
=======================

PartCAD currently supports two types of providers -- entities that can provide
parts and assemblies -- ``store`` and ``manufacturer``. ``store`` quotes and
orders parts from existing lists, by ``vendor`` and ``SKU``. ``manufacturer``
quotes and orders parts from their 3D model, by making them -- 3D printing
them, for instance.

.. code-block:: yaml

  # partcad.yaml

  parts:
    existing_part:
      vendor: homedepot # for example
      sku: ...
      count_per_sku: 25 # if it's sold in packs of 25
      ...
    new_part:
      manufacturing:
        method: additive
      parameters:
        color: black
        material: //pub/std/manufacturing/material/plastic:pla
      ...

Assemblies that are sold in an assembled state are declared the same way, using
``vendor`` and ``sku`` on the assembly itself.

See :ref:`procurement` for more information about declaring purchasable
objects, and :ref:`providers` for more information about the providers and how
PartCAD selects them.

In the future, PartCAD will support ``assembler``, which is supposed to produce
an assembly given assembly instructions and using parts ordered from
``store``-s and ``manufacturer``-s.

Currently, the provider has to be explicitly specified in the quote or order
request, or explicitly specified as one of the suppliers in the package where
the parts are declared, or in the package of the assembly they are procured for:

.. code-block:: yaml

  suppliers:
    myGarage:                     # a provider of this package
    ../provider_store:myGarage:   # one next door
    //vendor/store:myGarage:      # one anywhere

A supplier is written from the point of view of the package that lists it, and
is resolved against that package the way every other reference it makes is: a
bare name is one of its own providers, while a qualified one lets it buy from a
provider defined elsewhere instead of declaring one of its own.

A package served by a repository plugin has no ``partcad.yaml`` to write this
in, so its plugin states the same section in the package's ``meta``, and it is
read the same way (see :ref:`repositories`):

.. code-block:: json

  {"desc": "Metric hex bolts", "suppliers": {"//pub/svc/commerce/homedepot:homedepot": {}}}

A package that builds assemblies out of somebody else's parts can say where to
buy them, too. When ``pc supply`` breaks an assembly (or a scene) down into what
it is procured from, every one of those parts is looked for first at the
suppliers of the package the assembly is declared in, and then at the ones its
own package names. So a package of models built from a parts library that knows
nothing of a particular store can still be quoted at that store:

.. code-block:: yaml

  # The models' own package: none of its parts is declared here.
  suppliers:
    //pub/svc/commerce/homedepot:homedepot:

  assemblies:
    shelf:
      type: assy

A part asked for on its own, rather than as part of an assembly, is looked for
at its own package's suppliers only, and so is every part ``pc test`` checks.

In the future PartCAD will be able to select providers based on the location and
preferences of the requester, while leaving the possibility to enforce the use
of a specific provider for corresponding parts (for example, for parts that are
using a patented design).

Examples
========

`examples/provider_store <https://github.com/partcad/partcad/tree/main/examples/provider_store>`_
declares a ``store`` provider and parts bought from it;
`examples/provider_manufacturer <https://github.com/partcad/partcad/tree/main/examples/provider_manufacturer>`_
declares a ``manufacturer`` and parts it makes from their models.

Agent skills
============

``/pc:validate``
  Reads the bill of materials, which is what is procured, as part of giving a
  requirement its verdict.
