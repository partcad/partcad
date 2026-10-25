# Memory and scheduling: design

This is the design record for how PartCAD spends a machine's memory on a large design, and how it decides what to run
next. It starts from a measurement -- `pc render -r` of
[partcad-ldraw-examples](https://github.com/partcad/partcad-ldraw-examples) on a 16 GB machine -- and ends in a plan.
How to *use* any of it is the user documentation's job; this file is for whoever changes it.

Status words used below: **built** is on `devel`; **decided** is agreed and not built; **open** is not agreed.

Where it stands: step 1 is #849, the pull request that adds this record; steps 2 and 3 are #850; step 4 is being
done separately. Steps 5 to 7 are **open**: the first proposal for them is withdrawn, and section 9 says what
is wanted instead and the design being discussed.

## Contents

1. [The problem](#1-the-problem)
2. [What was measured](#2-what-was-measured)
3. [Where the memory goes](#3-where-the-memory-goes)
4. [The plan at a glance](#4-the-plan-at-a-glance)
5. [Step 1: release and share in the sandbox](#5-step-1-release-and-share-in-the-sandbox)
6. [Step 2: the daemon and the wire](#6-step-2-the-daemon-and-the-wire)
7. [Step 3: the disk cache](#7-step-3-the-disk-cache)
8. [Step 4: the swap healthcheck](#8-step-4-the-swap-healthcheck)
9. [Steps 5 to 7: scheduling, reconsidered](#9-steps-5-to-7-scheduling-reconsidered)
10. [The example repository and the parts library](#10-the-example-repository-and-the-parts-library)
11. [Validation](#11-validation)
12. [Open questions](#12-open-questions)

## 1. The problem

`pc render -r` of partcad-ldraw-examples -- a 731-part castle and a 237-part Technic car, built from the LDraw
library, and 33 pictures of them and of their sub-assemblies -- runs out of memory on a machine with 16 GB or less.
That repository's CI runs it with an 8 GB swap file added for the purpose, and with a `threadsMax` it believes keeps
three drawings at once (and which has been raised to four since 0.8.238).

Three things combine:

1. **Each job is heavier than it needs to be.** A sandbox drawing the castle decodes 731 separate copies of nine
   distinct bricks, and the meshing and the hidden-line removal then do their work for every copy; the daemon sends
   it a request with a base64 copy of the brick for every placement, and holds that request twice over while it
   waits for a sandbox to run in.
2. **Nothing about memory decides what runs.** The only strict limit is a count of sandbox processes
   (`threadsMax`, one per core by default and never fewer than four), so four of the biggest drawings can be admitted
   together on any machine.
3. **New work is not kept from overtaking old.** A recursive render starts every picture of every package at once.
   Builds and drawings of unrelated objects interleave, and which waiter gets the next sandbox is decided by polling
   with backoff -- effectively at random -- so many large objects are half done at the same time, each holding its
   share of the daemon's memory, instead of a few being finished.

The nested-wait deadlock -- N waiters holding the N slots of a pool, each waiting for work that cannot get one -- was
ended for the cases known by #834 (0.8.238, two days before this record): a slot waiting for work gives itself back,
and the pool runs over its size meanwhile. None of the runs below stalled. Section 9 keeps the pools as they are and
puts the decisions about memory and order where they belong, at the sandbox processes.

## 2. What was measured

**Where.** A cloud machine with 16 GB of RAM, a 13.4 GB memory limit on the cgroup the work ran in, 4 cores, no swap
and no Docker daemon, so the `venv` sandbox. PartCAD 0.8.240 from `devel`, default configuration (so four sandbox
processes at once), `PC_DAEMON_IDLE_TIMEOUT=0` as the examples' CI sets it. partcad-ldraw-examples at `8bc2963`.

**How.** A sampler recorded the RSS and PSS of the daemon, the client and every sandbox process once a second, with
which wrapper and which output file each sandbox was working on. For the largest drawings, the request the daemon
sends the sandbox was captured from an in-process run and replayed through `wrapper_export.py` itself, with the peak
memory recorded per phase. The scripts are in `dev-tools/profiling/` (section 11).

**`pc render -r`, today:**

| run | outcome | time | peak (PSS) | lowest available | pictures written |
| --- | --- | --- | --- | --- | --- |
| cold (empty `~/.partcad`) | killed by the OOM killer, twice | 1,567 s, of which ~660 s provisioning the sandbox | 13.6 GB | 1.0 GB | 29 of 33 |
| warm (shapes cached) | killed by the OOM killer | 208 s | 13.7 GB | 1.5 GB | 25 of 33 |

The cold run lost the four views of the whole car (`f1`, `f1-front`, `f1-right`, `f1-top`). The four had waited for
the same tree, became ready in the same second, and were admitted together into the four slots, each growing past
3 GB on its way to about 6 GB. The warm run lost `f1/car.png` instead, killed at 5.6 GB while `castle.png` (3.2 GB),
`front-end.png` (2.9 GB) and `castle-front.png` ran beside it. Which job dies changes from run to run, because which
jobs run together does.

One kill costs more than one picture. `Project.render_async` gathers a package's pictures without
`return_exceptions`, so the first failure ends the package's render: the warm run's one kill abandoned three drawings
that were one to two minutes into their work, and the four views that had not started yet.

**The jobs** (peak RSS of each sandbox, cold run; the jobs the warm run finished agree within 10%):

| job | peak | time |
| --- | --- | --- |
| `f1/car.png` (polygonal) | 6.1 GB | 174 s |
| `castle.png`, `castle-front.png` (polygonal) | 3.5 GB | 97-115 s |
| `f1.png` and its three views (polygonal) | over 3.3 GB when killed; probably about 6 GB, like the car | -- |
| `f1/front-end.png` (polygonal) | 3.1 GB | 70 s |
| `f1/drivetrain.png`, `f1/tub.png` (exact) | 3.1 GB | 58 s |
| `f1/front-frame.png` (exact) | 2.2 GB | 44 s |
| an LDraw Technic part, built from its `.dat` file | up to 2.1 GB | up to 474 s |
| any drawing of a small sub-assembly | 0.55-0.9 GB | 2-20 s |

An interpreter that has loaded the render stack and drawn nothing much is about 0.45 GB RSS (0.3 GB PSS, the rest
being libraries shared with its siblings), and that is the floor under every job.

**The daemon** peaked at 895 MB: the trees of the models being drawn, and the request of every drawing in flight held
twice (section 6.2). The cold run also logged four times that a shape "has been in preparation elsewhere for 60s;
going on without its cache key" -- the backstop of #834 firing, for `f1` (once for each of its three views) and for
`f1/car`. Both were then built without a cache key, so neither could be cached.

**No run stalled.** The nested-wait deadlock did not occur in any of these runs, at the four slots that are now the
floor; what ended them was memory.

**With step 1.** The same warm run with `decode_tree` sharing geometry (5.1): **completed, 260 s, peak 7.6 GB, never
under 7.5 GB available**, all 33 pictures written. The largest job is now an exact drawing (`f1/drivetrain.png`,
2.9 GB), and the whole models are 1.4-1.9 GB each. The daemon still peaked at 923 MB, which is step 2's.

## 3. Where the memory goes

Replaying the castle's request (`castle.png`, polygonal) phase by phase, today:

| phase | peak | time |
| --- | --- | --- |
| interpreter and imports (OCP, build123d, reportlab) | 451 MB | 4.4 s |
| read the request and parse it (33 MB of JSON) | 479 MB | 0.3 s |
| decode the tree: base64, zstd, BREP, for all 731 leaves | 835 MB | 3.0 s |
| **mesh and hidden-line removal** (`BRepMesh`, `HLRBRep_PolyAlgo`) | **3,362 MB** | **91.8 s** |
| edges to SVG (build123d) | 3,377 MB | 3.0 s |
| parse the SVG (svglib, 2.4 MB of it) | 3,404 MB | 4.9 s |
| rasterize (renderPM) | 3,405 MB | 1.1 s |

and the car (`f1/car.png`) is the same shape with bigger numbers: 1,058 MB decoded, **5,970 MB** after the projection,
6,041 MB at the end, 141 s.

Three things follow.

1. **The projection is the job.** Everything after it adds tens of megabytes; everything before it, a few hundred.
2. **It is paid per placement.** The castle is 731 placements of 9 distinct parts, and each placement is decoded into
   a shape of its own, so the mesh and the hidden-line data are built 731 times. Sharing the nine (5.1) takes the
   projection from 2.5 GB to 0.7 GB.
3. **The request is mostly copies.** 33 MB for the castle, of which 4.6 MB is distinct geometry: every leaf carries
   its part's BREP in base64. On the daemon's side, that is held while the drawing waits for a sandbox (6.2).

An exact drawing (`reproducible: true`) is different: `f1/tub.png` is 3.0 GB for 40 parts, and sharing takes it to
2.9 GB. The exact algorithm's memory follows the number of edges in the picture, and every triangle of a sewn LDraw
mesh has three (section 10).

## 4. The plan at a glance

| Step | What | Where | What it buys | Risk |
| --- | --- | --- | --- | --- |
| 1 | Release and share in the sandbox | `wrappers/ocp_serialize.py`, `wrapper_export.py`, `builtin/render` | a smaller peak per drawing (section 5) | low: one polygonal picture changes by 39 pixels |
| 2 | The daemon and the wire | `shape_envelope.py`, `shape.py`, `runtime*.py`, `cache_shape.py` | requests and cache entries one copy per distinct part; nothing serialized before it can run | medium: wire and cache format |
| 3 | The disk cache | `shape.py` render/export path, `cache_artifacts.py` | an unchanged picture is not drawn again | low |
| 4 | The swap healthcheck | `healthcheck/swap.py` | the user is told | low |
| 5-7 | Scheduling | `sandbox_lock.py`, the fan-out sites, `sync_threads.py` | every core busy, started work first, fewer tasks than cores only at capacity | open: section 9 |

Steps 1 to 4 are independent and each pays for itself; step 1 alone is what got the examples through on this machine
(section 2). Steps 5 to 7 are what makes the result hold for the next, larger design rather than for this one.

## 5. Step 1: release and share in the sandbox

### 5.1 Decode each distinct shape once (the change that matters)

`ocp_serialize.decode_tree` -- which `wrapper_export` runs for every output, and `decode_shape` beside it -- turns
every leaf of the tree into a TopoDS shape of its own: 731 independent copies of the castle's nine bricks, each with
its own faces, so that meshing triangulates each copy and the hidden-line removal builds its data for each copy. Keyed
by the payload, the same BREP read once and placed with `Located()` gives OCCT what it was built for: one `TShape` per
distinct part, shared by every placement, so the triangulation and everything derived from it exist once.

Measured with the request the daemon really sends (section 2), replayed in the sandbox:

| drawing | algorithm | peak today | peak shared | time today | time shared | picture |
| --- | --- | --- | --- | --- | --- | --- |
| `castle.png` (731 parts, 9 distinct) | polygonal | 3,405 MB | 1,416 MB | 104 s | 57 s | byte-identical |
| `f1/car.png` (236 parts, 39 distinct) | polygonal | 6,041 MB | 1,667 MB | 141 s | 57 s | byte-identical |
| `f1/tub.png` (40 parts, 13 distinct) | exact | 3,008 MB | 2,934 MB | 43 s | 41 s | byte-identical |
| `castle-front.png` (the castle from another camera) | polygonal | 3,401 MB | 1,408 MB | 86 s | 46 s | 39 pixels differ |

The polygonal drawings -- every whole model and every view of one -- lose 60 to 72% of their peak and half their time.
In the full run with sharing, 32 of the 33 pictures came out byte for byte as they are checked in. The one that did
not, `castle-front.png`, differs in 39 of its 218,112 drawn pixels, the same 39 every time: the polygonal algorithm
breaks ties between coincident faces -- a brick standing exactly on another -- in the order it meets them, and
sharing changes that order. A polygonal drawing is not promised to be reproducible in the first place
(`reproducible: false`), but the examples check theirs in, so the pull request carrying this re-renders that one
picture and says why. The exact drawings barely move: `HLRBRep_Algo` keeps per-edge data for every
placement whether or not the geometry is shared, and that is what fills them (see section 10 for the lever that does
reach them).

The same sharing is already done by `wrapper_gltf.py` for the viewer, keyed by `payload_digest`; this does it for
`decode_tree`, `decode_shape` and `wrapper_interference.py`, which still decode per node. What has to be checked is
that no implementation modifies a shape it was handed in place, since a change to one placement would now be a change
to all of them: the built-in exporters write files from the shapes and modify none; `cae_support.prepare()` imprints
sketches on a *part*, which has one placement. The key is the payload string as it arrived, so two different
geometries are never confused; hashing it is not needed in the sandbox.

### 5.2 Release what is no longer needed

The request text, the parsed JSON and the base64 of each BREP stay alive until the implementation returns, and so do
the geometry and the hidden-line data while the SVG is rasterized. Dropping them is a few lines in `wrapper_export` and
`render_raster`, and it was measured too: **20 to 40 MB** on the castle, because once 5.1 is in, none of these is
large. It is not where the memory is, and it is not in the pull request.

### 5.3 What was looked at and is not worth it

The SVG round trip of a PNG -- write an SVG, parse it with svglib into reportlab's object model, rasterize that -- was
the first suspect, and it is not one: the castle's SVG is 2.4 MB, and parsing and rasterizing it add under 50 MB to a
3.4 GB process. Drawing straight onto a cairo surface would change every checked-in picture once for no gain worth
having.

## 6. Step 2: the daemon and the wire

### 6.1 One copy of each distinct shape in a tree

In the daemon an assembly's tree shares one `bytes` object per part only for as long as it was built in this process;
a sub-assembly read back from the cache arrives as JSON, with a payload per leaf. The castle's tree in memory holds 476
distinct payload objects for 9 distinct contents (25.2 MB where 4.6 MB would do), and on the wire and in the cache
every leaf carries its own base64 copy.

The tree already has the arrangement that fixes this, for the other form a shape takes: a glTF tree carries a table of
geometry on its root (`KEY_GEOMETRY`) and each node names its entry (`KEY_GLTF_REF`). The same for BREP -- a `breps`
table on the root, keyed by a digest of the compressed payload, and a `brepRef` on each leaf -- measured on the
captured requests:

| request | today | with a table |
| --- | --- | --- |
| `castle.png` | 33.0 MB | 8.7 MB |
| `f1.png` | 66.1 MB | 15.5 MB |
| `f1/car.png` | 64.2 MB | 13.6 MB |
| `f1/tub.png` | 12.4 MB | 3.6 MB |

It is a property of the serialized document only. In memory every node keeps its own `brep`, and the nodes that came
out of one table entry hold the one object. `shape_envelope.dumps(share=True)` and `ocp_serialize.dumps(share=True)`
write the table; both ends' `loads()`, and `ocp_serialize.deserialize_raw()`, take it back out before anything walks
the tree, so no reader of a tree meets it. It is written only where the reader is known to understand it: requests to
PartCAD's own Python wrappers (renders, exports, analyses, routes and the viewer's glTF), and every wrapper's answer,
since the core reads both forms. A container implementation or a JavaScript one is handed the request as it always
was. It is written only when it makes the document smaller, so a document with nothing repeated is unchanged.

### 6.2 Nothing serialized before it can run

`Shape._run_implementation_locked` serializes the request and only then asks the runtime for a sandbox, which waits
for the environment lock and a process slot. Every drawing that is waiting therefore holds its whole request as text,
and the runtime adds a `bytes` copy for the pipe (`stdin.encode()`). That is what the daemon's 895 MB at the peak of
the run was: four views of the car in flight, at about 66 MB of text and 66 MB of bytes each, on top of the trees.

So a runtime's standard input may be a callable, which `runtime.stdin_bytes` calls as the process starts -- inside
the process slot, after the environment lock -- and the render path passes one. With the table of 6.1 as well, a
drawing of the car costs the daemon about 15 MB while it runs and nothing while it waits.

### 6.3 Smaller things in the same place

- `pc_logging.debug("Output of %s: %s" % (cmd, stdout))` and the lines beside it formatted the whole output of every
  sandbox -- a part's BREP, base64 -- whether or not debug logging was on. They take arguments instead.
- Not done, and recorded: the memory tier keeps every entry under 100 MB for the life of the context, and a warm
  daemon never drops a context (the TODO in `core/session.py`). A byte budget for the tier, least recently used out
  first, with `Shape._wrapped` let go along with its entry, would bound what a long-lived daemon accumulates. It
  changes the lifetime of every shape a context holds, which is a change of its own.

## 7. Step 3: the disk cache

### 7.1 Cache the pictures

`pc render` draws every picture every time, even when nothing it is drawn from has changed: only the IDE's thumbnails
are cached (`thumbnail.py`, `ctx.cache_renders`). The machinery for caching an output already exists and is used by
`pc cae`, `pc cam` and `pc sim` (`cache_artifacts.py`): a key made of the subject's cache key, the implementation, the
content of its script and of the wrapper, the code versions, and the request less the geometry; an entry holding the
result and the files the run wrote.

Using it for the `render:` section means a warm `pc render -r` of the examples, with nothing changed, starts no
drawing sandbox at all -- and the examples' CI already restores `~/.partcad/cache` between runs. A picture is a few
hundred KB, well inside the tiers' windows. Exports are left out: an exporter may write files beside the one it was
asked for (a URDF's meshes), and the cache holds the one. A picture is remembered only when the run succeeded and the
file was written by it, so a file an earlier run left at the path is never handed out as this one's.

### 7.2 Let the big trees into the file tier

The castle, `f1`, `f1/car` and `f1/front-end` trees are never written to the file cache: each is over
`cacheFilesMaxEntrySize` (10 MB), because of the copies in 6.1. So a warm run puts them together again from their
sub-assemblies every time. A tree entry is therefore a frame of its own (`cache_shape._TREE_MAGIC`): the tree as
compressed JSON in which each node names its payload, then each distinct payload once, as raw bytes rather than
base64. The castle's entry fits easily; `f1`'s distinct geometry alone is 10.9 MB of compressed BREP, so it still does
not, and the remedy for that is an entry that names its parts' own cache entries instead of carrying them. An earlier
release reading a framed entry counts it a miss and writes its own form; the frame reads both.

### 7.3 Later: geometry by path rather than by pipe

For the local sandboxes (venv, conda, none), every BREP a request names is already a file in the cache's directory.
Handing the sandbox paths rather than payloads would make a request a few kilobytes and let the sandbox read each part
once from disk. The `remote` sandbox and docker's `upload` mode still need the payloads inline, and two ways of
delivering geometry are two ways to get it wrong, so this is recorded rather than proposed.

## 8. Step 4: the swap healthcheck

A new check, `Swap`, in `src/partcad/healthcheck/swap.py`, beside `CpuCores` and shaped like it: warning severity,
never failing the run, tags `memory`, `swap`, `performance`.

- **What it asks.** Whether this machine can page at all: `psutil.swap_memory().total` (psutil is already a runtime
  dependency). Zero is the finding. On Linux it also asks the cgroup the process runs in, because a container on a
  host with swap may still be forbidden to use it: `memory.swap.max` of `0` (cgroup v2), or
  `memory.memsw.limit_in_bytes` equal to `memory.limit_in_bytes` (v1). macOS pages to swap files it creates on
  demand, so a total of zero there means "none used yet" rather than "none possible", and the check passes.
- **What it says.** "No swap is enabled. PartCAD designs can be large -- a drawing of a 700-part assembly takes several
  GB -- and without swap, work that needs more memory than the machine has is killed instead of slowed down. Enabling
  swap is strongly advised.", followed by the commands for the platform (a swap file with `fallocate`/`mkswap`/`swapon`,
  or zram, on Linux; the page file setting on Windows) and a suggested size (the size of RAM, on a machine with 16 GB
  or less).
- **Where it runs.** Where every healthcheck runs, on the client, because a check diagnoses the machine it runs on.
  A remote daemon's memory is its own; `pc daemon status` is where that would be reported, and is out of scope here.
- **Tests.** `tests/partcad/unit/test_healthcheck_swap.py`, after `test_healthcheck_cpu_cores.py`: no swap warns, swap
  passes, a cgroup that forbids swap warns, macOS passes, the check is discovered, the severity is a warning.
- **Docs.** A paragraph in `docs/source/troubleshooting.rst` beside the other checks, and the same advice where
  `features.rst` discusses `threadsMax`.

This is independent of everything else here and can land first.

## 9. Steps 5 to 7: scheduling, reconsidered

The first version of this record proposed admitting sandbox processes against a memory budget held below the
machine's RAM, and replacing the thread pools with one scheduler. Both are withdrawn. A budget below RAM holds back
cores long before the machine is out of memory, and PartCAD's threading exists to keep every core of a large machine
busy -- 64 of them as much as 4 -- without oversubscribing them; a design that gives that up is not what is wanted.
What is, as it now stands:

1. **Every core stays busy.** As many sandbox processes run as there are slots (`threadsMax`) while there is work
   for them, as today.
2. **What is started is finished first, without idle cores.** While the castle occupies only a few cores, the car's
   tasks use the rest. When the castle fans out into more tasks, new starts go to the castle: the car's running tasks
   are left to finish and none of its tasks are started in their place, so the number of car tasks in flight falls,
   to none if need be.
3. **Memory throttles only at capacity.** Fewer tasks than cores are kept in flight if, and only if, the memory in use
   reaches capacity -- and swap counts as capacity.

The design being discussed, **open** in every part:

- **A task is one sandbox launch** -- what occupies a core. The coroutines and threads that wait for sandboxes are
  not tasks and are not counted; nothing in the daemon computes geometry.
- **Admission in the order of roots, then depth-first within one.** A root is one unit of a command's outermost
  fan-out: one picture of `pc render -r`, one package of `pc test -r`. Roots rank by when their first task started,
  and roots not started yet by declaration order; within a root a task ranks by its position in the order one slot
  would reach it. When a slot frees, the first ready task in that order takes it. That is points 1 and 2 as they
  stand: the castle takes every slot it has ready work for, the car the slots the castle cannot use, and nothing
  running is pre-empted for it. A task building something that a better-ranked task waits for -- a brick two pictures
  need -- ranks as the better of the two (priority inheritance), or a castle picture would wait behind the car's turn.
- **Memory is watched against RAM plus swap**, the machine's or the cgroup's, whichever is smaller. Capacity cannot be
  waited for -- the kernel kills when it is reached -- so the trigger is a margin short of it, and what follows
  escalates: first no task is started, so tasks in flight fall below the core count as they finish; then the
  lowest-ranked running task is paused (`psutil.Process.suspend()`; in a container, the task's own process and not
  the container, since one sandbox container serves every task with its image and mounts) -- a paused task
  stops growing, and with swap its pages are the first to go out, which is the room the tasks ahead of it need -- and
  resumed when memory comes back; and last, at a critical margin, the lowest-ranked task is stopped and queued again,
  so that what is killed is PartCAD's choice rather than the kernel's, which may be the daemon. The best-ranked running
  task is never paused or stopped, which is what guarantees progress.
- **Today's pools stay.** Since #834 they are deadlock-free at any size, and they are what point 1 is about. What
  changes is around them: the rank travels with work across a thread hop, beside the OpenTelemetry context that
  `sync_threads._Work` already carries; `ProcessSlots` wakes its waiters in rank order instead of letting whichever
  polls first win; a shape's lock and a preparation lend their waiters' rank to the holder. Whether the pools should
  one day give way to a single event loop per request is a question of its own, and none of this needs it.
- **A failed task is one failure.** Whatever is decided above, `Project.render_async` should gather a package's
  pictures with `return_exceptions`, as `_render_packages_async` already gathers packages, and raise the first failure
  once the rest are done: today the first exception ends the package's render, which is how one kill in the warm run
  cost eight pictures (section 2). A task stopped at the critical margin is queued again rather than failed, but a
  real failure should not take its neighbours with it either. It is a few lines, and independent of the rest.

The questions it leaves are in section 12.

## 10. The example repository and the parts library

**partcad-ldraw-examples.** Its CI job carries two workarounds for this problem, and both comments have gone stale:

- `threadsMax: 3`, with "Three is the fewest it works with: with two, a render waits on itself and never finishes."
  Since 0.8.238 (#834) the floor is four and a lower value is raised to it with a warning, so the job already runs four
  sandboxes at once; and nested waits no longer deadlock at any size. The value does nothing today, and can go.
- An 8 GB swap file, "Paging is slower than having the memory, and much better than the kernel killing a drawing".
  That stays: it is exactly what the `Swap` healthcheck will recommend.

Nothing in the repository has to change for steps 1 to 4, with one exception: the release carrying step 1 draws
`castle-front.png` 39 pixels differently (5.1), and the examples' CI renders with the latest PartCAD, so that picture
is re-rendered and committed once that release is out. The `partcad: ">=0.8.191"` floor would rise to the release
carrying step 3 if the job is to rely on the picture cache.

**The parts library** (`//pub/universe/lego`, partcad/partcad-ldraw). An LDraw part is a mesh, and `ldraw.py` sews it
into a solid of triangular faces (`_solid_from_mesh`), so every flat face of a brick arrives as many triangles, and
every triangle edge is an edge the hidden-line removal has to process. That is what makes the castle 248,000 edges and
the car 423,000 (the numbers `partcad.yaml` gives for why they cannot be drawn exactly), and the exact algorithm's
memory grows with the edges, by that file's own account quadratically. Merging coplanar triangles into one face per
plane as the solid is built would reduce the edges of every brick, and every drawing of every LEGO model with them --
the one lever found that reaches the exact drawings, where sharing (5.1) does not.

It is not a one-line change. A first try, `ShapeUpgrade_UnifySameDomain` at its default tolerances on the decoded
parts of `f1/tub`, merged *no* faces on the four Technic parts it got through and reduced their edges by 2 to 8%;
on the fifth it did not finish. Why was not investigated -- the likeliest reason is that every triangle is built on
a plane of its own, which the default tolerances do not take for the same plane.
So the merging belongs in `ldraw.py` itself, before sewing, where coplanar triangles are known by their vertices --
it already finds planar loops for the caps it adds (`_cap_planar_loops`). That is a change to that repository, keyed
by its code version so every part is rebuilt once; it is recommended here and not planned, because it is not this
repository's code, and its effect is not measured.

## 11. Validation

- **The measurement is repeatable.** The scripts behind section 2 are in `dev-tools/profiling/` (see its README): a
  sampler of every PartCAD process's memory, a report of what it recorded, a driver that captures the exact request
  the daemon sends a render sandbox, and a harness that replays it phase by phase. A pull request that claims to move
  these numbers quotes them before and after.
- **Scheduling is unit-tested without a machine to fill**, once it exists: the admission takes its memory probe and
  its process control as parameters, so tests drive it with scripted numbers -- rank order with spare slots; a fan-out
  taking new starts from a later root without stopping its running tasks; the pause, the resume and the stop at the
  margins; the progress guarantee. `test_sync_threads.py` and `test_nested_build.py` keep holding the pools to being
  deadlock-free at sizes one and two.
- **End to end.** `pc render -r` of partcad-ldraw-examples, default configuration, completes on a 16 GB machine with
  no swap -- which it does with step 1 -- and, once scheduling is built, inside an 8 GB cgroup with swap, where today
  it is killed.
- **Pictures.** Nothing here may change an exact (`reproducible: true`) picture, and `Examples (PartCAD)` fails if
  one does. A polygonal one may change once, by the tie-breaking 5.1 describes, and the pull request that changes it
  re-renders it and says so -- `castle-front.png` in partcad-ldraw-examples, measured at 39 pixels.

## 12. Open questions

1. **Sharing geometry in the sandbox** (5.1) makes every placement of a part the same OCCT shape. No built-in
   implementation modifies what it is handed; an implementation published by another package might. #849
   states "do not modify the shapes you are handed" as part of the implementation contract. Acceptable, or
   should sharing be something an implementation opts into?
2. **Caching pictures** (7.1) means `pc render` can write a file without running anything. #850
   turns it on, as the shape cache is on; `--cache-bypass` and the tier switches apply. Right default?
3. **What ranks a root** (section 9): when its first task started, or where it is declared? The first is what
   "finish what is started" says; the second is simpler and nearly always the same order.
4. **What a root is** for `pc render -r`: each picture, or each top-level object with all of its pictures?
5. **The margins.** "At capacity" has to mean "a margin short of it", because at capacity the kernel acts first.
   Something like the larger of 512 MB and 2% of RAM plus swap to stop starting and pause, and half that to stop a
   task?
6. **Pausing before stopping.** Pausing loses no work but holds memory; stopping frees it and loses the task's time.
   Pause first, stop only at the critical margin -- or stop straight away?
7. **Predicting.** A task that ran before has a recorded peak. Is postponing one whose recorded peak would take the
   machine past capacity still "throttling only at capacity", or should admission look at the present and nothing
   else?
8. **Thrashing.** With swap counted as capacity, a machine can be far from capacity and making almost no progress,
   paging. Does sustained memory pressure (Linux PSI, `/proc/pressure/memory`) count as being at capacity?
9. **Several daemons on one machine** -- a daemon per workspace -- each schedule their own work against the same
   memory. Is that acceptable, with each reacting to what the machine reports, or do they need to agree on ranks?
