.. _product-lifecycle:

#################
Product Lifecycle
#################

.. toctree::
   :maxdepth: 2
   :hidden:

   requirements.rst
   design.rst
   analysis.rst
   manufacturing.rst
   validation.rst
   operations.rst


A product's life is a sequence of questions, and PartCAD keeps the answer to
every one of them in the same place: the declaration of the object the question
is about. This chapter takes the phases one at a time.

The phases are an order of **questions** rather than an order of work. Nothing
has to be finished before the next thing starts, and no phase is ever closed:
each is asked of the same object, and asked again whenever anything it depends
on changes. A part whose script changed is a part whose mass, whose analyses,
whose bill of materials line and whose checks are all out of date at once, and
PartCAD's answer to that is not a notification -- it is that none of those
answers was stored to begin with.

.. list-table::
   :header-rows: 1
   :widths: 18 44 38

   * - Phase
     - The question it asks
     - Where it is answered
   * - :doc:`Requirements </digital_thread/lifecycle/requirements>`
     - What does this have to be and do, in the words of whoever asked for it?
     - ``requirements:`` on the object, written before the design
   * - :doc:`Design </digital_thread/lifecycle/design>`
     - What *is* it: its geometry, its parameters, how it connects?
     - the part's script or file, an assembly's links, sketches, scenes
   * - :doc:`Analysis </digital_thread/lifecycle/analysis>`
     - What does engineering say about it?
     - ``physics:``, materials, ``fea:``, ``dynamic:``, ``thermal:``, ``cfd:``
   * - :doc:`Manufacturing </digital_thread/lifecycle/manufacturing>`
     - How does it come to exist -- what is bought, what is built, in what order?
     - ``manufacturing:``, ``vendor:``/``sku:``, materials, instructions
   * - :doc:`Validation </digital_thread/lifecycle/validation>`
     - Is it what it claims to be, and does it do what it is supposed to?
     - every claim above, checked by ``pc test``, ``pc sim`` and ``simulate:``
   * - :doc:`Operations </digital_thread/lifecycle/operations>`
     - How is the thing that was made actually doing?
     - nothing yet; the phase is reserved

The order is the order of *dependency*, which is why it reads the way it does:
a design is judged against requirements, an analysis is run on a design, what is
manufactured is what was designed and analysed, and validation is the question
whether the whole chain holds. Read backwards it is the more useful statement:
nothing downstream of a change survives it.


Three ways into every phase
===========================

Each phase can be worked on three ways, and every chapter below says what they
are for that phase:

**The Digital Thread panel.** The panel of the :ref:`PartCAD IDE <partcad-ide>`
and of the :ref:`Visual Studio Code extension <vscode-extension>` is this list of
phases, as a strip of tabs over whichever object is selected. Five of them are
always there -- **Design**, **Analysis**, **Manufacturing**, **Validation** and
**Operations** -- and **Requirements** appears in front of them for an object
that declares any. Most of the five open a **second strip** of their own
underneath, and every tab of it has a chapter here, under the phase it belongs
to: the object three ways under Design, the four analyses under Analysis, the
five steps from a decision to an instruction book under Manufacturing, and the
two ways of checking under Validation. **Operations** is shown disabled, because
there is nothing in it yet.

Each of those chapters is written the same way -- what the tab shows (**In the
UI**), what the same answer is called from a terminal (**On the command line**),
and which **agent skills** work in it -- because those are the three ways in,
and they are three ways to the same answer rather than three features.

**The command line.** Every tab is a ``pc`` command with a window around it, and
the command is the one to reach for in a script, in CI, or when the answer
matters more than the picture. :doc:`/cli` is the full reference.

**Agent skills.** A :doc:`skill </ai_agents/skills>` is a procedure an AI coding
agent follows, and the skills PartCAD ships are grouped by the phase they serve.
A skill runs the same commands, so nothing it produces depends on the agent that
ran it.
