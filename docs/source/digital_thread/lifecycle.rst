#################
Product Lifecycle
#################


The phases are an order of questions rather than an order of work: each is
asked of the same object, and asked again whenever anything it depends on
changes.

#. **Requirements.** What the object has to be and do, from the point of view of
   whoever asked for it, written before the design is.
#. **Design.** What the object is: its geometry, how it is parameterised, how it
   connects to other objects.
#. **Analysis.** What engineering says about it: what it weighs, how it carries a
   load, how it behaves once the world is switched on.
#. **Manufacturing.** How it comes to exist: what is bought and what is built,
   how each part is made and from what, in what order it is put together.
#. **Validation.** Whether the object meets what was asked of it, and whether
   every claim the declaration makes holds.
#. **Operations.** How the thing that was made is doing. The Digital Thread
   reserves a tab for it; nothing is collected yet.

The Digital Thread panel of the :ref:`PartCAD IDE <partcad-ide>` and of the
:ref:`Visual Studio Code extension <vscode-extension>` is this list, as a strip
of tabs over whichever object is selected: **Requirements** (for an object that
declares any), **Design**, **Analysis**, **Manufacturing**, **Validation** and
**Operations**.
