.. _dt-design-2d:

##
2D
##

**2D** is the object rendered to a picture, by the same code and with the same
options as ``pc render``. Where the :doc:`3D tab </digital_thread/lifecycle/design_3d>`
draws geometry the window has been sent, this one asks PartCAD for a *file* and
shows it -- so what is on screen is exactly what the command would write, and
the **Save…** button writes it wherever you choose.

In the UI
=========

A format is chosen from a list: **PNG**, **JPEG** or **SVG**. The picture is
zoomed with the mouse wheel, dragged with the pointer, and put back with a
double-click.

The tab has the same tree down its left as the 3D tab, and it means the same
thing: what is ticked is what is drawn, and a port ticked here is a port drawn
on the picture -- what ``pc render --with-ports`` and ``--with-internals``
produce. The :ref:`view panel <dt-design-3d>` applies as well: the axis buttons
are the views ``pc render --view`` names, so the picture after clicking **-Y**
is the picture ``--view front`` draws, and a section set on the 3D tab is drawn
cut here too, because PartCAD cuts the solid rather than the image.

.. image:: /images/dt-design-2d.png
  :width: 100%
  :align: center
  :alt: The Design group's 2D tab: the object rendered to a picture, with the format chooser and Save

It is for a part, an assembly, a scene or a sketch.

On the command line
===================

.. code-block:: shell

  pc ide view --design-2d :bracket              # this tab
  pc render -t png :bracket                     # the same picture, as a file
  pc render -t svg --view front :bracket        # from the view the -Y button gives
  pc render -t png --with-ports :bracket        # with the ports drawn on

:doc:`/config_output` describes every :ref:`file type <output-files>` and the
options each takes, including how a package's own ``render:`` section states
them once for every object in it rather than on each command.

Agent skills
============

``/pc:render``
  Produces the pictures -- several views of one object, since a single
  projection hides whatever is behind it. It is how every generating skill
  checks what it wrote, and how ``/pc:validate`` gathers the evidence for a
  requirement nothing can measure.

``/pc:describe``
  Writes an object's ``summary:`` from its measured size and these renders.
