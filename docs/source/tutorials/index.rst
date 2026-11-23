#########
Tutorials
#########

A tutorial builds one product from an empty directory to a verdict, a step at a time, and every step is shown three
ways: in the :ref:`PartCAD IDE <partcad-ide>`, on the command line, and through an AI agent's skills. Each one is
written to be followed from beginning to end; to look up how one particular thing is done, see the
:doc:`/tutorial` instead.

.. toctree::
   :maxdepth: 1
   :hidden:

   printed_stand.rst

:doc:`A printed stand under load <printed_stand>`
  A 3D-printed stand, shaped like a table, carries a block of steel in the middle of its top. You model the stand
  and the block, say how the stand is printed, put the two together in an assembly, show in a simulation that nothing
  moves, and turn what the simulation measured into a stress analysis of the stand. The analysis first finds that a
  light print would break, which printing denser fixes; then that the top sags too far, which no infill fixes and a
  thicker top does. It teaches materials and interfaces, ``basic`` and ``boolean`` parts, a part that *is* its print,
  an assembly, a simulation, an FEA scenario -- written by an agent skill or by hand -- strength and stiffness as two
  separate questions, and ``pc qual test`` failing and passing for the same reasons the IDE shows.
