########
VSCodium
########

`VSCodium <https://vscodium.com/>`_ is a build of the same source Visual Studio Code is built from, with
Microsoft's branding, telemetry and marketplace configuration removed, published under the MIT license. The
PartCAD extension runs in it exactly as it does in Visual Studio Code -- it is the same ``.vsix`` -- and
everything in :doc:`/tools_vscode` applies here too.

Two things differ, and both are about where extensions come from.

==========
Installing
==========

The easiest way is to let PartCAD do it, which fetches the ``.vsix`` from the GitHub release rather than from
a marketplace:

.. code-block:: shell

  pc ide install --with codium

With no ``--with``, ``pc ide install`` takes the first of ``partcad-ide``, ``codium`` and ``code`` it finds on
the ``PATH``, so on a machine with only VSCodium that is already VSCodium. By hand:

.. code-block:: shell

  codium --install-extension partcad-<version>.vsix

=================
The marketplace
=================

VSCodium is configured for `Open VSX <https://open-vsx.org/>`_ rather than the Visual Studio Marketplace,
whose terms restrict it to Microsoft's own products. So
``codium --install-extension PartCAD.partcad-official`` resolves against Open VSX, and what is published
there may lag the Visual Studio Marketplace. Installing the ``.vsix`` from the
`release <https://github.com/partcad/partcad/releases>`_ -- which is what ``pc ide install`` does -- sidesteps
that and is always the current version.

The same holds for the extensions PartCAD works alongside. Pylance in particular is proprietary and licensed
for Microsoft's products only, so it is not available here; open-source Python type checking is.

=======================
Or take the whole thing
=======================

The :ref:`Desktop Application <partcad-ide>` *is* VSCodium -- rebranded, with the PartCAD extension, the
extensions PartCAD works with, and the command line tools already inside it, opening in the PartCAD
workbench. If you are installing VSCodium in order to use PartCAD, install that instead and skip this page.
