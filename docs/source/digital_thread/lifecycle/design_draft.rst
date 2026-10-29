.. _dt-design-draft:

#####
Draft
#####

**Draft** is a dimensioned technical drawing of a part or an assembly -- the
drawing somebody is handed to make the thing, with its views laid out, its
dimensions and its title block.

PartCAD does not draw it. A **drawing package** does, the way an export
implementation writes a file (see :doc:`/plugins/output`), and the tab names the
one it used.

In the UI
=========

**Drawn by** names the drawing package: ``//pub/feature/render/draftwright``
unless you choose or type another, exactly as ``pc render -e`` names one. The
formats offered are whatever that package declares -- PDF, SVG and DXF for
draftwright -- and **Save…** writes the file.

A picture is shown on the tab and can be zoomed, dragged and put back with a
double-click. A PDF or a DXF cannot be drawn there; it is saved and opened in
another program instead.

.. image:: /images/dt-design-draft.png
  :width: 100%
  :align: center
  :alt: The Design group's Draft tab: a dimensioned drawing, with "Drawn by" above it

The first drawing takes a few minutes, while PartCAD installs the drawing
package into the sandbox it runs in; afterwards it is as quick as any other
render, and cached under everything it depends on. A drawing package lays its
views out itself, so the :ref:`view panel's <dt-design-3d>` axis buttons and
viewpoint are disabled here and say why -- a section is not, and the drawing is
made of the cut object.

On the command line
===================

.. code-block:: shell

  pc ide view --design-draft :bracket                                  # this tab
  pc render -t pdf -e //pub/feature/render/draftwright :bracket        # the same drawing
  pc render -t dxf -e //pub/feature/render/draftwright :bracket        # another of its formats

Agent skills
============

``/pc:render``
  Asks for a drawing like any other rendered file.
