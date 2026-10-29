.. _dt-manufacturing-bom:

#################
Bill of Materials
#################

**Bill of Materials** is what has to be procured in order to have the object:
every line item, counted. It is :doc:`/config_bom` as a tab, and the same answer
``pc bom`` prints.

What it is *not* is a list of parts. A part that is made is its **stock** --
you buy the sheet, not the panel cut out of it -- and a sub-assembly that
declares a ``vendor:`` and an ``sku:`` is one item ordered whole, with nothing
inside it looked at. What is built and what is bought comes from
:doc:`Build vs Buy </digital_thread/lifecycle/manufacturing_bvb>`; where
nothing was chosen, a line that can be either is bought.

In the UI
=========

One row per line item, with how many of each. For a part or an assembly.

.. image:: /images/dt-manufacturing-bom.png
  :width: 100%
  :align: center
  :alt: The Manufacturing group's Bill of Materials tab: every line item, counted

On the command line
===================

.. code-block:: shell

  pc ide view --manufacturing-bom :robot    # the tab itself
  pc bom robot                              # the same list
  pc bom -p size=M4 robot                   # of a parametrized variant

:doc:`/config_bom` explains how interfaces, ``alias`` and ``enrich`` make a line
item interchangeable -- an abstract position in the bill of materials that a
concrete part fills.

Agent skills
============

``/pc:validate``
  Reads the bill of materials as part of giving a requirement its verdict: a
  line of it is evidence for a feature that no measurement can judge.
