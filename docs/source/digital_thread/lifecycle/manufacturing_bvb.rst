.. _dt-manufacturing-bvb:

############
Build vs Buy
############

**Build vs Buy** is the first of the Manufacturing tabs, and the one the other
four follow from: for every part, piece of stock and sub-assembly the object is
made of, a switch saying whether *you* are going to make it or buy it.

It is the one decision in the whole Digital Thread that is **not** in the
package. The package says what can be bought and how what can be made is made;
which of the two a particular person chooses is a fact about who has which
machines, so it is kept on the machine of whoever made it. A checkout does not
carry it, and two people can build the same product differently without the
product differing.

In the UI
=========

Every line is one thing the object is made of, with a picture of it, how many
are needed, its size, its weight and its material, and a **Build** / **Buy**
switch.

- A line that can only be bought, or only be built, has its switch fixed and
  says why -- a part with a ``vendor:`` and no ``manufacturing:`` cannot be
  made here, and one with a ``manufacturing:`` and no supplier cannot be
  bought.
- A line that can be neither is marked **Incomplete**. That is the useful
  failure of this tab: it is where a part nobody can obtain shows itself,
  before anybody orders anything.
- Building a line brings in what *it* is made of -- its stock, its own parts --
  and buying it hides them, because what is bought is bought whole.

.. image:: /images/dt-manufacturing.png
  :width: 100%
  :align: center
  :alt: The Manufacturing group's Build vs Buy tab: a line per item, each with a picture and a Build/Buy switch

The choices are written under ``~/.partcad/garage/default/bvb/``, one file per
object, and ``pc instructions`` reads the same files -- which is what makes it
write the steps for what you are building rather than for everything the
package could build. Where nothing has been chosen, a line that can be either
is **bought**, which is what the bill of materials assumes.

On the command line
===================

There is no ``pc`` command that makes these choices, and that is deliberate:
they are the one input to this phase that is nobody else's to guess. What reads
them is:

.. code-block:: shell

  pc ide view --manufacturing-bvb :robot    # the tab itself
  pc instructions robot                     # the steps for what you chose to build
  pc bom robot                              # what has to be procured, given those choices

Agent skills
============

No skill chooses. ``/pc:validate`` reads the bill of materials and the assembly
instructions that follow from whatever was chosen, as part of giving a
requirement its verdict.
