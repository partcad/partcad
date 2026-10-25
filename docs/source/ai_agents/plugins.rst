#######
Plugins
#######

A plugin is the other way to get the :doc:`/ai_agents/skills` into an agent: installed into the agent itself, rather
than into the repository you are working in. Which one you want depends on who the skills are for -- a plugin
is yours, on this machine, for every package you open; the copies ``pc init`` writes belong to the
repository, so everybody who clones it gets them.

Both end up running the same commands from :doc:`/cli`.

===========
Claude Code
===========

.. code-block:: text

  /plugin marketplace add partcad/partcad@plugin-dist
  /plugin install pc@partcad

Then ``/pc:setup`` puts ``pc`` on this machine -- and, when it is run from a Visual Studio Code or VSCodium
terminal, :ref:`the extension <vscode-extension>` into that editor -- ``/pc:init`` starts a package, and
``/pc:gen a mounting bracket with four M4 holes`` writes the CAD script, renders several views of what came
out and checks them against what was asked.

.. note::

  The PartCAD repository is the marketplace -- there is no hosted catalog to search PartCAD for. The
  ``plugin-dist`` branch is republished by every release and contains no symlinks, which is what makes it
  install identically on Windows.

Two other ways to install the same plugin:

* ``/plugin marketplace add partcad/partcad`` reads the catalog out of the source tree. That copy shares its
  skills with the vendor-neutral library through a symlink, so it needs a checkout where git created one --
  on Windows, ``git config core.symlinks true`` before cloning.
* Every `release <https://github.com/partcad/partcad/releases>`_ carries a ``pc-<version>.zip``, and
  ``claude --plugin-url <url>`` loads one for a single session. That is how to try a version without
  installing it.

The plugin is versioned with everything else in the release that publishes it, so the plugin and the ``pc``
command line tool state the same version when they came from the same release.

======
Cursor
======

Cursor reads skills from ``.cursor/skills`` in the repository, which is where ``pc init`` puts ``pc``-prefixed
copies of the same library. There is nothing else to install:

.. code-block:: shell

  pc init --skills-only

See :doc:`/ai_agents/skills` for what gets written, and for how re-running it retires what PartCAD no longer ships.

============
Other agents
============

The skills are plain ``SKILL.md`` directories, so any agent that reads them can use the library directly from
``ai-agents/common/skills`` in the PartCAD repository, or from the copies ``pc init`` installs.

For an agent that speaks the Model Context Protocol instead of reading skills, PartCAD serves MCP on stdio --
see :doc:`/ai_agents/mcp`.
