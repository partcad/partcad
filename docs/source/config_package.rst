#########################
Packages and dependencies
#########################

.. _packages:

========
Packages
========

The package is defined using the configuration file ``partcad.yaml`` placed
in the package folder.
Besides the package properties and, optionally, a list of imported dependencies,
``partcad.yaml`` declares a list of :ref:`objects` contained in this package.


.. code-block:: yaml

  name: <(optional) the package path this package expects to be seen at; see "The package name" below>
  desc: <(optional) description>
  private: <(optional) boolean flag to mark the package as private>
  url: <(optional) package or maintainer's url>
  poc: <(optional) point of contact, maintainer's email>
  partcad: <(optional) required PartCAD version spec string>
  pythonVersion: <(optional) python version for sandboxing if applicable; defaults to the version PartCAD pins, not the one it runs on>
  pythonRequirements: <(python scripts only) the list of dependencies to install>
  javascriptVersion: <(optional) Node.js major version for sandboxing if applicable>
  javascriptRequirements: <(JavaScript scripts only) the list of npm dependencies to install>
  chili3dVersion: <(Chili3D parts only) the version of Chili3D to render with>
  unless: <(optional) the conditions this package does not work under; see "Tags" below>

  dependencies:
      <dependency-name>:
          desc: <(optional) textual description>
          type: <(optional) git|tar|local|external, can be guessed by path or url>
          path: <(local only) relative path to the package>
          url: <(git|tar only) URL of the package>
          relPath: <(git|tar only) relative path within the repository>
          revision: <(git only) the exact revision to import>
          plugin: <(external only) reference to the repository plugin that serves this package>
          subfolder: <(external only) location within the repository, for hierarchies>
          includePaths: <(optional) Jinja2 include path>

  suppliers:
      <(optional) the providers to consider for this package's objects; a bare
       name is one of this package's own, "../sibling:name" is one next door>

  parts:
      <part declarations, see below>

  assemblies:
      <assembly declarations, see below>

  repositories:
      <repository plugin declarations, see below>

The package name
----------------

A package is always addressed by its **location** -- the package path at which
it was loaded, derived from its parent. For example, a package in the
subfolder ``gobilda`` of the package ``//vendor`` is addressed as
``//vendor/gobilda`` regardless of what it declares about itself.

The optional ``name`` field declares the package's **identity**: the package
path at which the package expects to be seen. It only takes effect when the
package is loaded as the root (the top-most package of the current context) --
this lets a package be developed standalone using the very same package path
its consumers will see it at. In every other case ``name`` does not change
where the package is loaded; the location always wins.

This makes it safe to vendor a package -- copy it into your own package tree to
drop a dependency or to follow your own naming convention:

* The vendored copy is loaded at its location in your tree, not at the ``name``
  it declares. If the same package is vendored at two locations (even at two
  different versions), each is an independent instance, addressed at its own
  location, and the two never interact.
* References the package makes to itself using its declared ``name`` are
  automatically redirected to the location where the copy was actually loaded.
  A vendored copy therefore uses itself, instead of silently pulling in another
  copy from the package path it was originally taken from.

As a consequence, a vendored package cannot reference the original copy of
itself by its declared ``name``: that package path always resolves to the local
instance. This is intentional -- referencing two copies of the same package at
once is almost always a mistake, and the alternative would be an implicit,
easily-missed dependency on the upstream package.

.. _templates:

=========
Templates
=========

``partcad.yaml`` is a Jinja2 template rendered to YAML before it is parsed, so a
package can generate declarations rather than write every one out. These names
are available while it is being rendered:

.. list-table::
  :header-rows: 1
  :widths: 30 70

  * - Name
    - What it is
  * - ``package_name``
    - The package path this package is being loaded at.
  * - ``partcad_version``
    - The version of PartCAD doing the rendering, whole: ``"0.8.77"``.
  * - ``partcad_version_major``, ``partcad_version_minor``, ``partcad_version_build``
    - The same version as its three numbers.
  * - ``partcad_version_at_least(...)``
    - Whether that version is the one given or newer. Takes a string,
      ``partcad_version_at_least("0.8.77")``, or the numbers themselves,
      ``partcad_version_at_least(0, 8, 77)``.
  * - ``PI``/``M_PI``, ``E``/``M_E``, ``SQRT_2``, ``SQRT_3``, ``SQRT_5``
    - The constants a CAD file keeps reaching for.
  * - ``INCH``/``INCHES``, ``FOOT``/``FEET``
    - Millimetres per imperial unit: 25.4 and 304.8.

The constants in the last two rows are also what a ``%...%`` expression can use
(see :ref:`expressions`): one table serves both, so a name that works in
``{{ ... }}`` works in ``%...%`` too.

A constant is named in upper case. That is the convention for every name in
that table and for any added to it: what is lower case in an expression is a
function (``sqrt``, ``sin``) or a parameter, and a parameter is as likely to be
called ``e`` as a constant is.

Serving two PartCADs at once
----------------------------

A package that wants a feature this release has and the last one did not has a
choice: raise its ``partcad:`` requirement, which takes the package away from
everyone who has not updated, or write both forms and pick between them.

.. code-block:: jinja

  {% if partcad_version_at_least("0.8.77") %}
  # ... declared the way this PartCAD can read ...
  {% else %}
  # ... declared the way every PartCAD can ...
  {% endif %}

A PartCAD older than these names defines none of them, and a template that names
one there fails to render at all. So a package that has to work on those asks
first -- Jinja2's ``and`` short-circuits, so the call is never made where the
name is absent:

.. code-block:: jinja

  {% set new = partcad_version_major is defined and partcad_version_at_least("0.8.77") %}

The comparison is made one number at a time, which is the whole point of having
it: ``0.8.9`` is *older* than ``0.8.77``, and every comparison of the strings
says the opposite.

.. note::

  ``partcad_version_at_least`` is a function rather than a Jinja2 macro, which
  is what it looks like it should be. A macro always renders to *text*, so a
  false one comes back as the string ``"False"`` -- which is not empty, and so
  is true to ``{% if %}``. A comparison that reads as its own opposite is not a
  thing to leave lying in a template.

==========
Validation
==========

``partcad.yaml`` is checked against a JSON schema
(``src/partcad_utils/schema/partcad.json``) that describes everything below:
which sections exist, which fields each kind of declaration takes, and which of
them exclude or require one another.

Run the check over a package, or over the file alone:

  .. code-block:: shell

    pc lint                          # every check, over the package
    pc lint -f PartcadSchema         # this one only
    pc lint --file partcad.yaml      # no package, no daemon - just the file

Every finding names the line and column it came from. ``partcad.yaml`` is a
Jinja2 template rendered to YAML before it is parsed (see ``includePaths``
below), so the checker renders it the way PartCAD does -- with the version and
constants it may name, and with the ``includePaths`` a package above gives it --
and reports each finding at the template line and column it came from. A part
marked ``manufacturable: true`` (on itself, on the package, or on a package
above) that is neither an ``alias`` nor an ``enrich`` has to say how it is had:
a ``manufacturing:`` section, or both a ``vendor:`` and an ``sku:``. It is the
same checker :doc:`ASSY files <assy>` go through, and the `PartCAD
extension for VS Code
<https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad-official>`_ runs it
on the open document -- so a mistyped section is underlined as it is typed,
including in the file that is stopping the package from loading at all. Set
``partcad.lint.enabled`` to ``false`` to turn that off.

============
Dependencies
============

Here are some examples of a dependency declaration in ``partcad.yaml``:

.. role:: raw-html(raw)
    :format: html

+--------------------+-------------------------------------------------------------------------------------------------------+
| Method             | Example                                                                                               |
+====================+=======================================================================================================+
|| Local package     | .. code-block:: yaml                                                                                  |
|| (in the same      |                                                                                                       |
|| source code       |   dependencies:                                                                                       |
|| repository)       |     other_directory:                                                                                  |
|                    |       path: ../../other                                                                               |
+--------------------+-------------------------------------------------------------------------------------------------------+
| GIT repository     | .. code-block:: yaml                                                                                  |
| :raw-html:`<br />` |                                                                                                       |
| (HTTPS, SSH)       |   dependencies:                                                                                       |
|                    |     other_repo:                                                                                       |
|                    |         url: https://github.com/partcad/partcad                                                       |
|                    |         relPath: examples  # where to "cd"                                                            |
+--------------------+-------------------------------------------------------------------------------------------------------+
| Hosted tar ball    | .. code-block:: yaml                                                                                  |
| :raw-html:`<br />` |                                                                                                       |
| (HTTPS)            |   dependencies:                                                                                       |
|                    |     other_archive:                                                                                    |
|                    |       url: https://github.com/partcad/partcad/archive/7544a5a1e3d8909c9ecee9e87b30998c05d090ca.tar.gz |
+--------------------+-------------------------------------------------------------------------------------------------------+

Each dependency becomes a subpackage of the current package. All subfolders of the current package are considered
subpackages (of the type `local`) if they contain a ``partcad.yaml`` file. Subfolders do not need to be explicitly
declared as a dependency, but may be declared to provide a more detailed description.

External packages
-----------------

A dependency of type ``external`` is a package whose contents are served by a
**repository plugin** instead of being read from a folder (``local``) or a
remote archive (``git``, ``tar``). Its ``plugin`` field references a repository
declared in the ``repositories`` section (see :ref:`repositories`):

.. code-block:: yaml

  dependencies:
    example:
      type: external
      plugin: :my_repo    # a repository declared in this package

  repositories:
    my_repo:
      type: basic

The package's objects (parts, sketches, assemblies, ...), its child packages,
and its metadata are all fetched from the plugin on demand, rather than being
enumerated up front. This keeps loading cheap even when the repository is large
or remote: a part is fetched only when it is actually used.

An external package can host a hierarchy. When its children are listed, the
plugin reports child package names; each child is imported as another external
package backed by the same plugin, with a ``subfolder`` that scopes its
requests within the repository. In this way one plugin can serve an entire tree
of packages, each with its own sketches, parts, assemblies, providers and
further children.

Non-null responses from a plugin are cached on disk, keyed by the plugin
reference and the request; a request the plugin has no answer for is remembered
only for the run that made it, and is put to the plugin again after a restart.
The same key also names the directory the plugin's own files are materialized
into, and a file already there is served without asking the plugin again.

The cache does not know when the plugin's code changes, so a plugin that starts
answering differently - a new field on every part it serves, or the same parts
measured another way - would keep being served the stale, pre-change entries.
The plugin says so itself, with a module-level constant in its script::

    # Raise whenever this plugin's answers stop meaning what they meant before.
    # v1 added the stud interfaces; v2 read the connectors off the geometry
    # instead of the name; v3 turned every part upright.
    CACHE_VERSION = 3

It is folded into the cache location, so raising it moves the whole repository
(and every child in its hierarchy) to a fresh cache namespace at once. It
defaults to ``0`` when the script names none, and a repository with no script of
its own - an ``enrich`` one, which rewrites another repository's answers - has no
code to version and stays at ``0``.

The number lives in the plugin because it is the plugin's own business. A
package that imports a plugin-backed library has no way of knowing that the
library now measures its parts differently, and should not have to be told: it
would have to be told again in every package that imports it, and each of them
would be a place to forget. So this is not a field of the dependency that
imports the plugin, and PartCAD reads it out of the script rather than asking
for it - the answer is needed before the first question can be asked. The script
is parsed, never executed.

See ``examples/plugin_repository_basic`` (a package backed by a local file),
``examples/plugin_repository_full`` (backed by an HTTP endpoint) and
``examples/plugin_repository_tree`` (a hierarchy of packages).

.. _repositories:

============
Repositories
============

A repository plugin serves the contents of a package: its objects, its child
packages and its metadata. It is what backs an ``external`` dependency (see
`External packages`_).

Repositories are declared in ``partcad.yaml`` using the following syntax:

.. code-block:: yaml

  repositories:
    <repository name>:
      type: <basic|enrich>
      desc: <(optional) textual description>
      parameters:  # (optional)
        <param name>:
          type: <string|float|int|bool>
          enum: <(optional) list of possible values>
          default: <default value>

``enrich`` repositories are references to other repositories with some
parameters modified to specific values.

``basic`` repositories are implemented as Python scripts, invoked the same way
as provider scripts (via ``runpy``, with the input in the global ``request`` and
the output in the global ``output``). A repository script answers a single,
generic key/value request:

- `request["api"] == "get"`
- `request["key"]`: the key being requested
- `output["result"]`: the value stored under that key (or ``null`` if unknown)

The keys address every kind of data uniformly, so serving a new kind of object
or a new piece of metadata needs no new API:

- ``objects/<kind>`` -- all objects of a kind, as ``{name: config, ...}``. The
  kinds are the ten in ``Project.OBJECT_KINDS``: ``material``, ``interface``,
  ``sketch``, ``part``, ``assembly``, ``scene``, ``provider``, ``repository``,
  ``software``, ``partType``
- ``objects/<kind>/<name>`` -- a single object's config, fetched without listing
  the whole repository
- ``deps`` -- the names of the child packages
- ``meta`` -- package-level properties (``desc``, ``render``, ``manufacturable``,
  ``suppliers``, ...), and ``objectKinds`` (see below)
- ``files/<path>`` -- the base64-encoded content of a file an object references
  by ``path``. A plugin-backed package has no source tree, so a file-backed
  object's file is fetched from the plugin and materialized into the package's
  cache directory when the object is built.

For a hierarchy, a child package's requests are prefixed with its
``subfolder``: a child in ``motors`` asks for ``motors/objects/part``,
``motors/deps`` and so on, all served by the same script.

Say which kinds a package has
-----------------------------

Every key is a separate run of the script, and a package has ten kinds of
object. Something as ordinary as listing the packages that hold anything to
look at asks after four of them, per package, and for a hierarchy of a hundred
packages that is four hundred runs -- most of them to be told "none".

A package's ``meta`` may therefore carry ``objectKinds``, the kinds that
package holds at all:

.. code-block:: json

  {"desc": "LDraw parts in the 'Brick' category.", "objectKinds": ["part", "partType"]}

PartCAD then answers "none" for every other kind without asking. This narrows
what is asked for and never what may be served: a plugin that lists a kind it
turns out to have none of is simply asked a question it answers emptily, and a
plugin that says nothing is asked about everything, as before. It is read out
of the metadata PartCAD has already fetched and is never worth a request of its
own, so a package reached on its own -- rather than through a traversal, which
reads ``meta`` for every package as it goes -- is queried exactly as it was.

Responses are cached per key (in memory and on disk), so a repository that is
slow or remote is queried as little as possible. See
``examples/plugin_repository_basic``, ``examples/plugin_repository_full`` (an
HTTP-backed repository) and ``examples/plugin_repository_tree`` (a hierarchy).
