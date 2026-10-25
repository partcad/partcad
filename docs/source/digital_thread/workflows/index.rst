#########
Workflows
#########

A workflow is a path through the phases of :doc:`/digital_thread/lifecycle`, and the chapters under this one take those
phases one at a time. These are the shapes the path takes in practice.


From an idea to a part
======================

#. Describe the part to an agent: ``/pc:gen-part`` (or ``/pc:gen-assembly``)
   writes the ``requirements:`` down from the description first, in its own
   terms, and only then models it (see :ref:`claude-plugin`).
#. ``pc test`` proves it builds, can be made, and has the ports, interfaces and
   physical properties it is required to have.
#. ``/pc:validate`` runs everything, looks at the part from every angle that
   matters, and gives each requirement a verdict -- met, not met, or "cannot
   tell", with the evidence named.

Changing a design without breaking it
=====================================

#. Edit the script or the declaration; the Digital Thread shows the object again
   as soon as it is saved.
#. Open **Validation**: every check runs again, through the cache, so what did
   not change is not asked again. A failure says what it found; an interference
   leaves an assembly of the two parts and what they share to look at.
#. ``pc test`` and ``pc sim`` in CI hold every change to the same checks, and
   rendered pictures checked in beside the package make a change in how anything
   looks a diff somebody reviews.

From a design to an order
=========================

#. **Manufacturing → Build vs Buy** decides, per part and sub-assembly, what is
   made and what is ordered; the choice is kept on the machine of whoever made
   it.
#. ``pc bom`` lists what that takes, ``pc supply quote`` asks suppliers for it,
   and ``pc supply order`` orders it.
#. ``pc instructions`` writes the book that puts it together, step by step, and
   ``pc cam`` the programs the machines cut its parts with.

Reviewing somebody else's product
=================================

``pc test -P <package>...`` checks every object of a package and everything below
it. In the Digital Thread, each object shows its requirements, its design, its
analyses, how it is made, and its checks with what each one found -- the whole
thread of one object on one screen.


.. toctree::
   :maxdepth: 2

   requirements.rst
   design.rst
   analysis.rst
   manufacturing.rst
   simulation.rst
   validation.rst
