Public Repository
#################

The public PartCAD repository is created and maintained by the community
based on the PartCAD standards and conventions. It is hosted on
`GitHub <https://github.com/partcad/partcad-index>`_.

==================
Nothing to install
==================

PartCAD retrieves the contents of this repository, and of every other repository and package a package
imports, as it needs them. No manual action is needed to "install" it: a package created by ``pc init``
declares the public index as a dependency, and the first command that needs something from it fetches it.

If you suspect something is wrong with the locally cached copy, ``pc system status`` says where the cached
files are, and ``pc system reset`` clears them.

==================
Who maintains what
==================

The top levels of the package hierarchy are expected to be maintained by the
PartCAD community.
Lower levels of the hierarchy are expected to be maintained by vendors and
other communities. PartCAD community does not aim to achieve the
uniqueness of parts and assemblies. Moreover, everyone is invited to provide
their alternative models as long as they provide a different level of model
quality or different level of package quality management processes, and as long
the package data properly reflects the quality that the maintainer provides and
commits to maintain. This way PartCAD users have a choice of which model to
use based on their specific needs.

====================
How it keeps working
====================

Every package in it is pinned to an exact commit, declares the oldest PartCAD
it works with, and keeps the branch the repository tracks working for everybody
who already uses it; a breaking change goes to a new branch instead. Changes are
merged to its ``devel`` branch, and ``main`` -- what packages created by
``pc init`` track -- only moves by fast-forward from it.
`CONTRIBUTING.md <https://github.com/partcad/partcad-index/blob/devel/CONTRIBUTING.md>`_
in the repository has the details, and :doc:`/digital_thread/change_management` gives the same
advice for a library of packages of your own.

Contributing a part, an assembly or an interface to it is covered in :doc:`/contributing`.
