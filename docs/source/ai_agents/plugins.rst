#######
Plugins
#######

A plugin (or an extension) is the other way to get the :doc:`/ai_agents/skills` into an agent: installed into the agent itself, rather
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

==========
Gemini CLI
==========

The same branch is a Gemini CLI extension too: its root holds a ``gemini-extension.json``, which is where
Gemini CLI looks for one, beside the Claude Code marketplace.

.. code-block:: shell

  gemini extensions install https://github.com/partcad/partcad --ref plugin-dist
  gemini extensions update partcad        # after a release

It carries every skill, as ``pc-<name>``; the MCP server, ``pc mcp``, for the workspace Gemini CLI is working
in; and a short ``GEMINI.md`` that tells the model what PartCAD is and that the skills exist. The extension is
versioned with the release, like the Claude plugin. It needs ``pc`` on ``PATH`` for its server -- the
``pc-setup`` skill installs it.

``pc init --agents gemini`` is the per-repository alternative: the skills in ``.agents/skills``, the server in
``.gemini/settings.json``, and ``AGENTS.md`` added to the files Gemini CLI reads.

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

GitHub Copilot, Codex, Zed, OpenCode and Devin Desktop (Windsurf) read skills from ``.agents/skills`` in the
repository, and Kiro from ``.kiro/skills``; ``pc init`` writes both (see :doc:`/ai_agents/skills` for which by
default, and ``--agents`` for the rest). None of them has a plugin to install.

Beyond those, the skills are plain ``SKILL.md`` directories, so any agent that reads them can use the library
directly from ``ai-agents/common/skills`` in the PartCAD repository. And an agent that reads no skills at all
but speaks the Model Context Protocol gets every one of them from ``pc mcp``, as a prompt and through its
``skill`` tool -- see :doc:`/ai_agents/mcp`.
