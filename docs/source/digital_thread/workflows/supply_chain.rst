############
Supply Chain
############


PartCAD currently supports two types of providers (entities that can provide
parts and assemblies): ``store`` and ``manufacturer``.
``store`` can be used to quote and order parts from existing lists:
by ``vendor`` and ``SKU``.
``manufacturer`` can be used to quote and order parts by using their 3D model
(for example, by 3D printing them).

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

See :ref:`procurement` for more information about declaring purchasable objects,
and :ref:`providers` for more information about the providers and how PartCAD
selects them.

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

In the future PartCAD will be able to select providers
based on the location and preferences of the requester, while leaving the
possibility to enforce the use of a specific provider for corresponding parts
(for example, for parts that are using a patented design).
