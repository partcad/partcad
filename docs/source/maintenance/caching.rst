.. _caching:

#######
Caching
#######


PartCAD is capable of caching intermediate and final results of all model compilations.
This can be particularly useful when working with large models or when scripting languages
(like OpenSCAD, CadQuery, build123d, Chili3D or sdf) are used.

Anything PartCAD produces in a sandbox is cached under the environment that
produced it as well as under its own inputs: the interpreter version and the
versions of the CAD libraries installed alongside it. That covers parts and
sketches written as scripts, and equally parts read from CAD files, since the
importer that turns a ``STEP`` file into geometry is itself a script in a
sandbox. Moving a package to another Python or Node.js, or to another version of
Chili3D, therefore re-renders rather than serving what the previous environment
built. ``pc info`` reports that environment for the objects that have one; an
assembly does not, because it is composed from objects that each carry theirs.

That environment is the one the package *declares*, not the sandbox that
happened to run: its interpreter version, its requirements, and the
``dockerImage`` it names, if any. The sandbox types (``conda``, ``venv``,
``none``, ``docker``, ``remote``) are expected to be reproducible and
equivalent, so switching between them, or between machines that use different
ones through a shared cache tier, finds the entries the other one wrote. A
``none`` sandbox running a host interpreter other than the one declared warns
about it and is cached as the declared one.

At the moment code-CAD caching is experimental and can be enabled by using the following configuration:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    cacheDependenciesIgnore: True

Cache tiers
===========

The cache is a hierarchy of tiers, each with its own switch, because what is
worth keeping in memory is not what is worth a file, and neither is what is
worth a network round trip:

======================= ============================================================ ==========
Tier                    Where it keeps things                                        Default
======================= ============================================================ ==========
``cacheMem``            This process's memory. Nearest, and lost on exit.            on
``cacheFiles``          A directory under the internal state directory. Local.       on
``cacheRemote``         A memcached server, shared by a team or a CI fleet.          off
``cacheS3``             An S3 bucket, which outlives all of the above.               off
======================= ============================================================ ==========

A read walks them in that order and stops at the first hit; a write offers the
entry to every tier whose size window accepts it. The two shared tiers are off
by default because they need an address that only a deployment can supply:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    cacheRemote: True
    cacheRemoteServer: memcached.example.com:11211

    cacheS3: True
    cacheS3Bucket: my-partcad-cache
    cacheS3Region: us-east-1

Each tier also takes ``...MaxEntrySize`` and ``...MinEntrySize`` to set the
window of object sizes it accepts, and the memcached tier takes
``cacheRemoteNamespace`` and ``cacheRemoteExpiration``. ``cacheS3`` additionally
accepts ``cacheS3Prefix`` and ``cacheS3EndpointUrl``, the latter for an
S3-compatible store that is not AWS.

``cacheRemote`` needs nothing installed. ``cacheS3`` needs the ``aws`` extra
(``pip install -U 'partcad[aws]'``); enabling it without that reports an error
naming the package to install and leaves the remaining tiers working. See
:doc:`/installation` for both.

A hit in a farther tier is copied into the nearer tiers that missed it, so an
entry another machine put in S3 is downloaded once and is a local file from
then on. Writes to the two shared tiers are sent in the background: a build
does not wait for memcached or S3, what is still waiting to be sent is visible
to the process that wrote it, and it is sent before PartCAD exits. What a
shared tier answered it does not hold is believed for a minute, so the many
lookups of entries that are usually absent -- a part's components, its
properties -- cost a round trip a minute rather than one each.

Cache keys
==========

An object is cached under a hash of what produces it: its configuration (less
the keys that only describe it, such as ``desc``), the environment it is built
in, and the files it is built from. A file contributes a digest of all of its
content, but never its path or its modification time, so a fresh clone on
another machine produces the same keys and a shared tier is shared. The digest
is worked out again only when the file changes, and a file of 1 MB or more is
not read again by the next process either.

An object made out of others is keyed on theirs as well: an ``extrude`` or
``sweep`` on its sketch, a ``compound`` part on its assembly, an ``assy``
assembly on everything it links to. Editing a part rebuilds every assembly that
uses it, and an object with ``cache: false`` makes everything built out of it
uncached too.

Exports, renders, analyses, routes and simulations
==================================================

What ``pc export``, ``pc render``, ``pc cae``, ``pc cam`` and ``pc sim``
produce is cached in the same tiers: the result (the warnings, the findings,
what the route implementation counted, or what the simulator reported) together
with the files the run wrote -- the exported file or the picture, the analysis
model, the route program, or the whole run directory of a simulation, with the
scene, its meshes and whatever the plugin left there. Asking the same question
again puts the files back where that run asks for them and runs nothing. The
analysis, ``cam`` and ``sim`` checks of ``pc test``, the IDE's analysis tabs,
and ``pc convert`` go through the same cache.

An exported or rendered file is cached together with anything its
implementation wrote beside it -- the meshes a URDF file names, the ``.bin``
next to a ``.gltf`` -- and that is only possible because the implementation
says what it wrote: an implementation returns ``files``, a list of paths
relative to the directory of the file it was asked for, and an empty list when
it wrote nothing else. Every implementation PartCAD ships says so. One that does
not -- written before this existed -- still works, and runs every time.

The file's name is not part of the question. The files an implementation writes
are named after the one it was asked for -- ``logo.urdf`` and
``logo_meshes/bolt.stl`` -- so what is kept is the part each adds to the name
they share, and asking for ``robot.urdf`` puts back ``robot.urdf`` and
``robot_meshes/bolt.stl``. A name ending differently -- ``xyz.JPEG`` for a
picture kept as ``abc.jpg`` with ``abc.colors.txt`` beside it -- leaves nothing
to name the other files by (a difference of case does not count), and neither
does a new name for files that name each other inside them, as a URDF file names
its meshes: either is produced again. A filtered view (``--filter``) is keyed as
the object it is a view of plus the links it keeps, and the pictures of an
assembly instruction book as the assembly and the step.

PartCAD's own sandboxed steps are cached the same way: the tessellation the IDE
draws an object with, the PDF of an assembly instruction book, and the length a
connection is pushed through. Those are keyed on exactly what the sandbox is
handed -- the text and the pictures of the book, the geometry of each shape --
so showing an object again, or printing the same book again, starts no sandbox.
The tessellation is kept a shape at a time, keyed on that shape's exact geometry
and on how finely it is drawn, so an assembly shown after one of its parts was
edited sends that part, and nothing else, to be tessellated again.

The question is the object's own cache key plus everything the run adds to it:
the boundary conditions and where they landed, a route's job and the machine it
is cut on, the implementation and every option it resolved to, the sandbox it
runs in, the content of its script, and every Python module of the package it
comes from -- the helper a plugin's scripts share as much as the scripts -- with
the commit that package is at when it was fetched from a repository, and the
version its script and the wrapper that runs it report (the ``CACHE_VERSION``
each states). Changing any of those runs it again, so a plugin release that
changed only a helper is seen. What a run writes into a package, a model or a
picture, is not part of the question, and neither is where the package is on
disk or when its files were last touched. A simulation's ``validation:`` is not part
of the question: it is evaluated again on every run, so editing it re-judges the
cached run rather than repeating it. What a simulation's question is made of,
and how ``pc test``'s verdict on one is kept, are in :ref:`sim-caching`.

Only answers are cached: an export, an analysis, a route or a simulation that failed is run again
next time, since installing a missing solver changes no key. An object with
``cache: false`` has nothing derived from it cached either. The tiers' maximum
entry sizes apply as usual -- a model larger than ``cacheFilesMaxEntrySize`` is
not kept in ``cacheFiles`` -- but their minimum sizes do not, because no
solver's answer is too small to be worth keeping.

``pc test`` also remembers each check's verdict on each object, and a failure it
remembers keeps what the check said about it: read back, it repeats the reason
and says that it was remembered from an earlier run. ``pc --cache-bypass test``
works every verdict out again.

``pc --cache-bypass <command>`` (or ``PC_CACHE_BYPASS=1``, or ``cacheBypass: True``)
bypasses every tier for one run: nothing is read from a cache and nothing built
is written to one.

The daemon keeps packages loaded between commands. Before each command it
compares the ``partcad.yaml`` of the packages the command is about, and of every
package they declare as a dependency, with what it read, by modification time
and size, and reloads a package that changed together with the packages
underneath it. Each package is compared at most once every 15 seconds.
