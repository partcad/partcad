.. _claude-for-manufacturing:

########################
Claude for Manufacturing
########################

`Claude for Manufacturing <https://claude.com/resources/articles/claude-for-manufacturing>`_ is a plugin
Anthropic publishes for the Claude app on Team and Enterprise plans. Its skills draft the paperwork of running a
plant -- quotes, requests for quotation and bid comparisons, quality reports and corrective actions, breakdown
diagnoses, production reports -- from the plant's own records, for a person to check before anything goes to a
customer or a supplier. It reads those records through connectors to Autodesk Fusion, Infor, Microsoft 365 and
Oracle NetSuite, or from exports saved where Microsoft 365 can reach them.

What it does not have is the product: the parts, what they are made of and how, what they are held to, and how
that changed. A product kept as PartCAD packages has all of that, and three of PartCAD's
:doc:`/ai_agents/skills` write it out in the form those skills read -- a folder of files with a manifest that
says where every figure came from. Neither plugin needs to know about the other: PartCAD writes the folder,
Claude for Manufacturing reads it.

.. list-table::
   :header-rows: 1
   :widths: 35 65

   * - Claude for Manufacturing asks
     - PartCAD answers with
   * - Quote a new job
     - ``/pc:quote-pack``: what building *N* of the product takes -- what is bought, priced where a supplier
       answers; what is made, from how much of which material; how many assembly steps -- with every rate left
       for the estimator
   * - Source from another supplier, compare bids
     - ``/pc:rfq-pack``: what a supplier quotes from -- a line per part with its quantity, method, material,
       finish and tolerance, a STEP file, a dimensioned drawing, and the assembly instructions when they assemble
       it too
   * - Investigate a failed inspection, a corrective action
     - ``/pc:change-impact``: what changed since the revision the batch was made to, which assemblies that
       reaches, how each bill of materials moved, and whether it still passes qualification; ``pc compare`` holds
       a scan of the part against its model (see :ref:`compare`), and ``/pc:validate`` the design against its
       requirements
   * - Compare design variations
     - ``pc compare`` and ``/pc:validate`` on the variants, and ``/pc:render`` to look at them
   * - Report on production
     - Nothing: PartCAD knows the product, not the machines making it

===============
Setting them up
===============

The two plugins usually belong to two different people -- an engineer who keeps the packages, and whoever
quotes, buys or inspects -- and the folder between them is the whole of the integration.

The engineer's side
===================

PartCAD's ``pc`` plugin, in the agent the packages are worked on in. In Claude Code:

.. code-block:: text

  /plugin marketplace add partcad/partcad@plugin-dist
  /plugin install pc@partcad
  /pc:setup

``pc init --skills-only`` puts the same skills into the repository instead, for every agent that opens it (see
:doc:`/ai_agents/skills`). Then, for example:

.. code-block:: text

  /pc:rfq-pack gearbox, 50 units, the machined parts, into ~/OneDrive/Engineering/RFQ
  /pc:quote-pack gearbox x 200
  /pc:change-impact since v1.3

Write the packs into a folder Microsoft 365 can reach -- a SharePoint library or a OneDrive folder synced to the
machine -- so the Microsoft 365 connector of Claude for Manufacturing finds them.

The plant's side
================

An administrator installs Claude for Manufacturing from the plugin directory, and someone tells Claude
"Set us up" (see `Anthropic's announcement <https://claude.com/resources/articles/claude-for-manufacturing>`_).
When it asks which systems the plant uses, say that product definitions come from PartCAD, and name the folder
the packs are written to: the quoting and sourcing skills then work from the packs as they would from any other
export.

One person, both plugins
========================

Claude's plugins page installs plugins from a GitHub marketplace, or from an uploaded ``.zip``. Every
`PartCAD release <https://github.com/partcad/partcad/releases>`_ carries the ``pc`` plugin as
``pc-<version>.zip``; upload it beside Claude for Manufacturing (`Use plugins in Claude
<https://support.claude.com/en/articles/13837440-use-plugins-in-claude>`_ says how, and what an administrator can
restrict). The ``pc`` plugin's skills then run in the same conversation as the manufacturing ones.

Its MCP server, ``pc mcp``, runs on the computer, so that computer needs PartCAD (``/pc:setup`` installs it).
The plugin starts the server for the project the session is in. If the server does not find your package there,
add it as a local server of its own with the package named by an absolute path, as for Claude Desktop (see
:doc:`/ai_agents/mcp`). The packs are written inside the package's workspace in that case, which is the only place
the server writes to unless it is started with ``--allow-path``.

=================
What is in a pack
=================

Each skill writes one folder, laid out the same way every time, so that whatever reads it next finds the same
thing:

``/pc:rfq-pack``
  ``cover.md`` (the request, for a person to read and send), ``lines.csv`` (one row per part: quantity, method,
  material, finish, stock, tolerance, size, mass), ``parts/`` (STEP, and 3MF for what is printed),
  ``drawings/`` (a dimensioned PDF per part, from ``//pub/feature/render/draftwright``), ``views/``, and
  ``assembly/`` when the supplier assembles it.

``/pc:quote-pack``
  ``costing.csv`` (one row per line: buy, stock, make, assemble, with order quantities rounded up to the packs
  each is sold in), ``quote-basis.md`` (known costs, unpriced lines, the cost drivers of what is made and
  assembled, and the rates left for the estimator).

``/pc:change-impact``
  ``ecn.md`` (a draft engineering change notice), ``bom-delta.csv``, and ``views/before`` and ``views/after``.

And each has a ``manifest.json``: the package, the object and its parameter values, the commit it was made from
and whether anything was uncommitted, the PartCAD version, and every file with the exact ``pc`` command that wrote
it. That is what lets the manufacturing skills cite where a figure came from, and what lets anyone produce the
same pack again from the same commit.

Three rules hold in all of them, because they are the same rules Claude for Manufacturing works by:

* **Nothing is made up.** Every number comes from a ``pc`` command. A tolerance nobody stated, a material that
  does not resolve, a price nobody quoted is written as unknown and listed under *Open items* -- never filled in.
  Labour and machine rates, margins, due dates, a change's disposition and effectivity are left blank for a
  person.
* **Nothing is sent or ordered.** The packs are for a person to review. ``pc supply quote`` is asked only with the
  user's agreement, and ``pc supply order`` never.
* **A pack names its revision.** It is made from a commit, and says so; made from uncommitted work, it says that
  first. Tagging the commit an RFQ was sent from is what lets ``/pc:change-impact`` answer "what changed since we
  asked for quotes" later.

===================
What it does not do
===================

* It does not write to an ERP or a system of record. A part number, a price or a supplier PartCAD learns of stays
  in the pack; entering it anywhere is a person's job, or another plugin's.
* It does not choose what is built and what is bought. That is the IDE's
  :doc:`Build vs Buy </digital_thread/lifecycle/manufacturing_bvb>` tab, saved on the engineer's machine, and the
  packs follow it.
* It does not nest parts on stock. One sheet or bar is counted for each part cut from it, so a stock quantity is
  an upper bound, and the pack says so.
