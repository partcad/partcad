.. _dt-design-cam:

###
CAM
###

**CAM** is what a part's machine makes of it: the print a filament printer lays
down along its route, what a router, a laser or a drill leaves of the stock, the
part a mold gives back of its cavity. It is there for a part that says it is made
that way -- ``manufacturing: method:`` ``additive``, ``subtractive`` or
``forming`` (see :doc:`/config_making`) -- and disabled, saying why, for anything
else.

The 3D tab draws a part as it is; this tab draws it as it comes off the machine,
with every setting that machine takes beside it, to change, to look at the
result of, and to save.

In the UI
=========

The middle is the 3D view, of the product rather than of the part, drawn at the
finer level of detail (see :ref:`Extra details <dt-design-3d-extra>`). A print is
drawn as the beads it is made of, and with only the faces anything can see: its
skin while it is whole, and what a section opens once it is cut -- the walls, the
skins and the infill, as sparse or as full as the settings make it.

Down the right is the same **view panel** as on the 3D tab -- the gizmo, the axis
views, the viewpoint, the sections, Animate, Auto-fit and Opacity -- without
**Extra details**, since what this tab draws is always the product, finely. The
sections are the Design group's, as they are on every other tab of it: a part
cut on the 3D tab is cut here too.

Down the left is **how it is made**:

- what the part is, in its own words (its ``desc:``);
- how it is made, by what and from what: printed on a filament printer after its
  design, cut on a router from its stock along a drawing, molded in a mold from
  its cavity;
- where its geometry is kept: in the file ``pc cam --materialize`` wrote, or made
  on demand;
- a field per **setting** of its machine, each in the units PartCAD reads it in
  (``0.2``, ``0.2 mm``, ``20%``), empty where the part states nothing and with what
  is taken then shown in it. Which settings a machine takes is what its schema
  says it takes, so a printer offers its axis, nozzle, filament, layer height,
  line width, walls, top and bottom layers, infill, infill pattern and feed; a
  router its cutter, depths, feeds, speed, stepover and operation; a mold its
  shrinkage. Pointing at a setting says what it is.
- **Save** and **Revert**, and under them what the product comes to: its layers,
  how much of its design a print deposits, how much filament that takes.

A setting changed is a setting **tried**: once the fields have settled, PartCAD
makes the part again with it -- nothing is written -- and the view shows what
that makes. So making the infill sparser and cutting the part through shows the
inside change. While it is made, the cursor and a notification say so; a setting
the machine does not take is said, in the words ``pc qual test`` uses, in place of
a picture.

**Save** writes what is tried into the part's ``manufacturing:`` section of its
``partcad.yaml`` -- under the machine's own subsection, ``fff:`` or ``mold:`` or
``cnc:`` -- keeping the rest of the file as it was written, comments included.
A field emptied takes that setting out. If the part's geometry has been
materialized -- its file is there -- Save writes it again too, with what was
saved, so that the declaration and the file cannot come to disagree. **Revert**
puts every field back to what the part states.

.. image:: /images/dt-design-cam.png
  :width: 100%
  :align: center
  :alt: The CAM tab: how a print is made and its settings, the print cut through to show its infill, and the view panel

On the command line
===================

.. code-block:: shell

  pc ide view --design-cam :print       # show it on this tab
  pc cam :print                         # the route its machine follows
  pc cam --materialize :print           # what that route makes, into the part's file
  pc qual test -f materialize :print    # whether that file is still what it makes

Save is what editing the ``manufacturing:`` section by hand does, followed by
``pc cam --materialize`` where the part was materialized.
