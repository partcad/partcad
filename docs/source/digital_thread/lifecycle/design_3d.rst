.. _dt-design-3d:

##
3D
##

**3D** is the shape itself, drawn in the panel and turned with the mouse. It is
the one tab that is always there: it arrives over the viewer protocol from
whichever ``partcad`` was asked to show the object, so even a shape shown from a
script -- something that belongs to no package at all -- has this tab and
nothing else.

Everything else in the Digital Thread is a question about a named object. This
is the object.

In the UI
=========

Down the left is **what is on screen**, with a checkbox on every line. The list
is the object itself: a part or a sketch is one line, an assembly or a scene a
line per thing it holds -- named as the ASSY file names it, as deeply as the
file nests them -- and an interface a line per port it is drawn with. Unticking
a line hides it and everything under it; ticking it again brings back exactly
what was showing before, and a tick drawn grey rather than solid says that
something underneath it is hidden.

Under each line is what that object says about connections: a line per
**interface** instance with its ports under it, and a ``ports`` line for the
ports belonging to no interface. Every port is drawn as a coordinate frame --
the same frames ``pc render --with-ports`` draws on a projection -- and a port
whose interface gives it a sketch shows that too, half see-through, in the blue
of its ``+Z``: the shape the connection happens across, which is what makes an
opening readable as one. The ``<ports>`` and ``<interfaces>`` lines start folded
up, because an assembly of forty parts has a frame at every hole of every one of
them and all of it at once shows nothing; an object's own ports start out drawn,
the ports of everything inside it do not.

Pointing at a part or a sub-assembly makes it **flicker** in the view, which is
how to tell which of the shapes on screen a line is without moving the camera.

Down the right is the **view panel**, folded away until the side bar button at
the top of that edge brings it out -- and then out on every tab at once. From
the top: an **orientation gizmo** to drag the view round, or click an axis to
look along it; a button per axis (**X**, **-X**, **Y**, **-Y**, **Z**, **-Z**),
which are the views ``pc render --view`` names; a two-ended **section** slider
per axis, starting at the faces of the bounding box, which cuts the exact
geometry before it is drawn rather than clipping the picture; the **viewpoint**
as ``viewport_origin``, ``viewport_up`` and a target, ready to be copied into a
``render:`` section or onto ``pc render --viewport-origin``; and **Animate** and
**Opacity**, which turn the model on its own and make it see-through.

.. image:: /images/dt-design-3d.png
  :width: 100%
  :align: center
  :alt: The Design group's 3D tab: the tree of what is on screen, the shape, and the view panel

The view uses the graphics card where the window can (WebGL, else WebGPU). In a
window that cannot -- a virtual machine, a remote desktop, a driver the editor
could not use -- it draws without one: flat-shaded and slower, and a big model
drawn as boxes while it is being turned. A note in the corner says so. A
`3Dconnexion <https://3dconnexion.com/>`_ **SpaceMouse** moves the model here
too; see :doc:`/tools_vscode`.

On the command line
===================

.. code-block:: shell

  pc ide view :bracket                  # show it, on whichever tab the panel is on
  pc ide view --design-3d :bracket      # show it on this tab
  pc info :bracket                      # what it is and what it measures
  pc render --with-ports :bracket       # the same ports, drawn on a picture

``pc ide view`` shows an object in the Digital Thread from a terminal, and
``pc ide state`` reports what the panel is showing -- including the boxes ticked
in this tree and a screenshot of the tab on screen, which is what an agent
working beside you reads.

Agent skills
============

``/pc:gen-part``, ``/pc:gen-assembly``, ``/pc:gen-sketch``
  Model from a description, and check what they wrote by rendering it from
  several angles rather than by looking at one.

``/pc:add-interfaces``
  Works the ports out of the geometry and proves them twice -- drawn on the
  part, and mated in a throwaway assembly -- which is what this tab shows.
