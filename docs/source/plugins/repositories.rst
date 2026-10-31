############
Repositories
############

A **repository plugin** serves the contents of a package: its objects, its child
packages and its metadata. It is what backs an ``external`` dependency -- a
package that is not a directory, not a git clone and not a tarball, but a script
PartCAD asks.

It is the most unusual of the plugin kinds, because it does not add a capability
to a package you write: it **replaces the package**. Everything else in PartCAD
reads a ``partcad.yaml`` and the files beside it; a plugin-backed package has no
source tree at all, and answers questions about itself instead.

:ref:`repositories` is the reference for the declaration and for every key the
protocol defines.

What a repository is for
========================

- **A catalogue nobody wants to check in.** A supplier's whole range is tens of
  thousands of parts; a plugin turns the supplier's own data into PartCAD
  objects on demand, and nothing is copied.
- **A live source.** An ERP system, a PLM database, an internal part register --
  the authority is the system, and the package is a view of it that is never out
  of date.
- **A generated family too large to enumerate.** Every size of a fastener, every
  length of a profile: the plugin answers for the one that was asked for.
- **A format that is already a table.** A CSV, a spreadsheet, a JSON dump: one
  short script turns it into a package.
- **A model site.** Thingiverse, GrabCAD, MakerWorld: a catalog nobody lists,
  searched with the site's own search and fetched one model at a time. Such a
  package serves no enumeration at all -- it answers a search, and the names the
  search hands back.

Using one
=========

A dependency of ``type: external`` names the plugin that serves it:

.. code-block:: yaml

  dependencies:
    example:
      type: external
      plugin: :my_csv        # a repository declared in this package

Everything below that is ordinary. The objects the plugin serves are listed,
inspected, rendered, tested and put into assemblies like any others:

.. code-block:: shell

  pc list parts example            # what the plugin serves
  pc list packages example         # its child packages, if it has a hierarchy
  pc list parts -r example         # recursively, through the whole hierarchy
  pc ide view example:bolt         # one of its parts

Writing one
===========

.. code-block:: yaml

  repositories:
    csv:
      type: basic
      desc: Parts read from a CSV file
      parameters:
        filename:
          type: string
          desc: The name of the CSV file to read the parts from.
    my_csv:
      type: enrich            # the same repository with a parameter fixed
      source: csv
      with:
        filename: example.csv

``basic`` repositories are Python scripts, run the way a provider script is --
with the input in the global ``request`` and the output in the global
``output``. ``enrich`` repositories are references to another repository with
some parameters fixed, which is how one script serves several packages.

**A repository script answers one generic key/value request.** There is no
method per kind of object:

- ``request["api"] == "get"``, ``request["key"]`` is the key being asked for
- ``output["result"]`` is the value, or ``null`` when the key is unknown

The keys address every kind of data uniformly, which is why serving a new kind
of object or a new piece of metadata needs no new API:

``objects/<kind>``
  Every object of a kind, as ``{name: config, ...}``. The kinds are the ten in
  ``Project.OBJECT_KINDS``: ``material``, ``interface``, ``sketch``, ``part``,
  ``assembly``, ``scene``, ``provider``, ``repository``, ``software``,
  ``partType``.

``objects/<kind>/<name>``
  One object's config, fetched without listing the whole repository. Answer this
  one and a package of ten thousand parts costs one request per part used.

``deps``
  The names of the child packages.

``meta``
  Package-level properties -- ``desc``, ``render``, ``manufacturable``,
  ``suppliers`` -- and ``objectKinds``.

``files/<path>``
  The base64-encoded content of a file an object references by ``path``. A
  plugin-backed package has no source tree, so a file-backed object's file is
  fetched from the plugin and materialized into the package's cache directory
  when the object is built.

``search/<kind>?q=<text>&limit=<n>``
  The objects the repository finds for a search, ``{name: config, ...}`` best
  first, for a package whose ``meta`` lists the kind under ``searchKinds``.
  ``pc search parts`` then asks the plugin rather than matching what it lists,
  which is what makes a catalog nobody can list searchable at all.

``objects/<kind>/<name>;<param>=<value>,...``
  One parametrized instance, for a package whose ``meta`` lists the kind under
  ``instanceKinds``: the plugin resolves it itself, so a parameter can choose
  another file or another format rather than only another value.

For a hierarchy, a child package's requests are **prefixed with its
subfolder**: a child in ``motors`` asks for ``motors/objects/part``,
``motors/deps`` and so on, all served by the same script.

Examples
========

Three example packages, in increasing order of realism.

``examples/plugin_repository_basic``
  A flat package of parts read from a CSV file. The whole plugin is one short
  script, ``csv.py``, and the data is ``example.csv`` beside it. It declares the
  repository twice -- a ``basic`` one taking a ``filename`` parameter, and an
  ``enrich`` of it with the filename fixed -- which is the pattern to copy. It
  also answers ``search/part``, so ``pc search`` asks it.

  .. code-block:: shell

    cd examples/plugin_repository_basic
    pc list parts example
    pc search parts -P example -k bolt
    pc ide view example:bolt

  The part it serves is an ordinary part in the Digital Thread -- the package it
  belongs to simply has no source tree:

  .. image:: /images/plugin-repository.png
    :width: 100%
    :align: center
    :alt: A part served by the CSV repository plugin, shown in the Digital Thread




``examples/plugin_repository_tree``
  The same idea with a hierarchy, which is where the subfolder prefix is
  exercised:

  .. code-block:: shell

    cd examples/plugin_repository_tree
    pc list packages example
    pc list parts -r example
    pc ide view example/motors:shaft

``examples/plugin_repository_full``
  The realistic one: the data is served by an HTTP endpoint (``server.py``) that
  the plugin (``remote.py``) calls, rather than hardcoded in the script. This is
  the shape an ERP or a PLM integration has. The endpoint has pytests of its own,
  independent of PartCAD, which is the other half of the lesson -- a plugin that
  talks to a service is two things to test, not one.

  .. code-block:: shell

    cd examples/plugin_repository_full
    python server.py &            # the endpoint, in another shell
    pc list parts example
    pc ide view example:cube
