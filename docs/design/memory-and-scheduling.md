# Memory and scheduling: design

This is the design record for how PartCAD spends a machine's memory on a large design, and how it decides what to run
next. It starts from a measurement -- `pc render -r` of
[partcad-ldraw-examples](https://github.com/partcad/partcad-ldraw-examples) on a 16 GB machine -- and ends in a plan.
How to *use* any of it is the user documentation's job; this file is for whoever changes it.

Status words used below: **built** is on `devel`; **decided** is agreed and not built; **open** is not agreed. Every
item of the plan is **open**: this is a proposal for review, and nothing in it has been implemented.

## Contents

1. [The problem](#1-the-problem)
2. [What was measured](#2-what-was-measured)
3. [Where the memory goes](#3-where-the-memory-goes)
4. [The plan at a glance](#4-the-plan-at-a-glance)
5. [Step 1: release and share in the sandbox](#5-step-1-release-and-share-in-the-sandbox)
6. [Step 2: the daemon and the wire](#6-step-2-the-daemon-and-the-wire)
7. [Step 3: the disk cache](#7-step-3-the-disk-cache)
8. [Step 4: the swap healthcheck](#8-step-4-the-swap-healthcheck)
9. [Step 5: admission by memory](#9-step-5-admission-by-memory)
10. [Step 6: finish what is started](#10-step-6-finish-what-is-started)
11. [Step 7: one scheduler instead of the thread pools](#11-step-7-one-scheduler-instead-of-the-thread-pools)
12. [The example repository and the parts library](#12-the-example-repository-and-the-parts-library)
13. [Validation](#13-validation)
14. [Open questions](#14-open-questions)

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

The nested-wait deadlock the request also mentions -- N waiters holding the N slots of a pool, each waiting for work
that cannot get one -- was ended for the cases known by #834 (0.8.238, two days before this record) by letting a
waiting slot give itself back and the pool run over its size meanwhile. That fix and a memory limit pull in opposite
directions, which is the reason for step 7.

## 2. What was measured

**Where.** A cloud machine with 16 GB of RAM, a 13.4 GB memory limit on the cgroup the work ran in, 4 cores, no swap
and no Docker daemon, so the `venv` sandbox. PartCAD 0.8.240 from `devel`, default configuration (so four sandbox
processes at once), `PC_DAEMON_IDLE_TIMEOUT=0` as the examples' CI sets it. partcad-ldraw-examples at `8bc2963`.

**How.** A sampler recorded the RSS and PSS of the daemon, the client and every sandbox process once a second, with
which wrapper and which output file each sandbox was working on. For the largest drawings, the request the daemon
sends the sandbox was captured from an in-process run and replayed through `wrapper_export.py` itself, with the peak
memory recorded per phase. The scripts are listed in section 13.

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

**With step 1 alone.** The same warm run with `decode_tree` sharing geometry (5.1), patched in for the measurement and
reverted afterwards: **completed, 224 s, peak 8.1 GB, never under 7.5 GB available**, all 33 pictures written. The
largest job is now an exact drawing (`f1/drivetrain.png`, 2.9 GB), and the whole models are 1.4-1.9 GB each.

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
mesh has three (section 12).

## 4. The plan at a glance

| Step | What | Where | What it buys | Risk |
| --- | --- | --- | --- | --- |
| 1 | Release and share in the sandbox | `wrappers/ocp_serialize.py`, `wrapper_export.py`, `builtin/render` | a smaller peak per drawing (section 5) | low: one polygonal picture changes by 39 pixels |
| 2 | The daemon and the wire | `shape_envelope.py`, `shape.py`, `runtime*.py`, `cache_shape.py` | requests and cache entries one copy per distinct part; nothing serialized before it can run | medium: wire and cache format |
| 3 | The disk cache | `shape.py` render/export path, `cache_artifacts.py` | an unchanged picture is not drawn again | low |
| 4 | The swap healthcheck | `healthcheck/swap.py` | the user is told | low |
| 5 | Admission by memory | `sandbox_lock.py`, then `scheduler.py` | no out-of-memory kill on a small machine; the biggest job still runs, alone | medium |
| 6 | Finish what is started | the fan-out sites, the admission queue | depth-first completion; the daemon holds only what can run | medium |
| 7 | One scheduler | `sync_threads.py`, `shape.py`, `concurrency.py`, the semaphores | the nested-wait deadlock gone as a class; limits that hold | high: several pull requests |

The proposed order is 4, 1, 2, 3, then 5 and 6 together, then 7 -- with one piece of step 5, a failed picture no
longer abandoning the pictures beside it (section 9), taken first because it is a few lines. The first four are
independent and each pays for itself; step 1 alone is what got the examples through on this machine (section 2).
Steps 5 and 6 are built on today's threading, so they help before the refactor and become its admission policy
afterwards. They are what makes the result hold for the next, larger design rather than for this one.

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
placement whether or not the geometry is shared, and that is what fills them (see section 12 for the lever that does
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
large. It is worth doing for the cost of it, and it is not where the memory is.

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

It is a change to the envelope, so it is made where the envelope is read and nowhere else: `shape_envelope` and
`ocp_serialize` build and resolve the table; `decode_tree` resolves references before an implementation sees the tree,
so `shape_tree` looks to an implementation as it does today; `deserialize_raw` callers get a `resolve_refs()` helper; a
cache entry without a table still reads. `cache_shape` writes the table form, which is also what lets the trees in
question be cached at all (7.2).

### 6.2 Nothing serialized before it can run

`Shape._run_implementation_locked` serializes the request and only then asks the runtime for a sandbox, which waits
for the environment lock and a process slot. Every drawing that is waiting therefore holds its whole request as text,
and the runtime adds a `bytes` copy for the pipe (`stdin.encode()`). That is what the daemon's 895 MB at the peak of
the run was: four views of the car in flight, at about 66 MB of text and 66 MB of bytes each, on top of the trees.

So the request is serialized under the lease, straight to `bytes`, and written to the pipe in chunks; the runtime's
`run_async` takes the payload as a callable producing it. With the table of 6.1 as well, a drawing of the car costs
the daemon about 15 MB while it runs and nothing while it waits.

### 6.3 Smaller things in the same place

- `pc_logging.debug("Output of %s: %s" % (cmd, stdout))` and the lines beside it format the whole output of every
  sandbox -- a part's BREP, base64 -- whether or not debug logging is on. They take arguments instead.
- `ShapeCache.write_async` serializes an entry before any tier is asked whether it would take an entry that size;
  for the castle that is a 33 MB JSON document built to be refused. The size can be known from the payloads first.
- The memory tier keeps every entry under 100 MB for the life of the context, and a warm daemon never drops a
  context (the TODO in `core/session.py`). A byte budget for the tier (`cacheMemoryMaxSize`), least recently used out
  first, with `Shape._wrapped` let go along with its entry, bounds what a long-lived daemon accumulates. Everything it
  evicts is in the file tier or can be put back together from its children.

## 7. Step 3: the disk cache

### 7.1 Cache the pictures

`pc render` draws every picture every time, even when nothing it is drawn from has changed: only the IDE's thumbnails
are cached (`thumbnail.py`, `ctx.cache_renders`). The machinery for caching an output already exists and is used by
`pc cae`, `pc cam` and `pc sim` (`cache_artifacts.py`): a key made of the subject's cache key, the implementation, the
content of its script and of the wrapper, the code versions, and the request less the geometry; an entry holding the
result and the files the run wrote.

Using it for `render:` and `export:` means a warm `pc render -r` of the examples, with nothing changed, starts no
drawing sandbox at all -- and the examples' CI already restores `~/.partcad/cache` between runs. A picture is a few
hundred KB, well inside the tiers' windows. The question it raises is in section 14.

### 7.2 Let the big trees into the file tier

The castle, `f1`, `f1/car` and `f1/front-end` trees are never written to the file cache: each is over
`cacheFilesMaxEntrySize` (10 MB), because of the copies in 6.1. So a warm run puts them together again from their
sub-assemblies every time. With the table, the castle's entry is 8.7 MB and fits; the car's is 15.5 MB and still does
not, which is why the entry should also be compressed (the payloads are zstd already, the JSON around them is not),
rather than the limit raised.

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

## 9. Step 5: admission by memory

Every sandbox launch already passes through one place, `sandbox_lock.process_slots.slot_async()` -- the Python, the
JavaScript, the docker and the remote sandboxes, KiCad's container, a plugin's. That is where the machine's memory
gets a say, and it can be built on today's threading, before step 7.

**What a launch asks for.** A lease of one CPU slot (`threadsMax`, as now) and an *estimate* of the memory it will
need. The estimate is, in order of preference:

1. what the same job took the last time -- the peak recorded for this implementation (the wrapper, plus the
   implementation script for an output) and this subject (the shape's cache key), kept as a small entry in the
   cache beside the shape;
2. otherwise a per-implementation ratio of peak memory to request size, learnt from every run of that
   implementation and kept the same way;
3. otherwise a floor, the size of an interpreter that has loaded the CAD stack (section 2: about 0.45 GB RSS,
   0.3 GB PSS).

**How a job is measured.** While a sandbox runs, the admission samples its memory about four times a second:
`psutil` over the process and its children, PSS where the platform has it, so that the shared libraries of four
interpreters are not counted four times. The peak is what is recorded. A container's own memory comes from the
container runtime; the remote sandbox reports the peak in its answer. Sampling is also what step 5's second half
watches.

**What may be admitted.** The budget is the smaller of the machine's memory and the cgroup's limit, less a reserve
(`memoryReserve`, default the larger of 1 GB and a tenth of the budget), optionally capped by `memoryMax` (and
`PC_MEMORY_MAX`); both are user configuration like `threadsMax`, and travel to the daemon with every request the same
way. The head of the queue is admitted when a CPU slot is free and its estimate fits in what is left: the budget, less
what the running jobs use, less what they are still expected to grow by (estimate minus current use, where positive),
and never more than the memory the system currently reports as available. **When nothing is running, the head is
admitted whatever its estimate**, so that a job bigger than the machine runs on its own -- into swap, where there is
some -- rather than never.

**Watching, not only predicting.** An estimate can be wrong, and the first run of a job has none. So the same sampler
watches the system as a whole:

- under a low watermark of available memory, nothing new is admitted;
- under a critical one, with more than one job running, the running job with the *lowest* priority (step 6) is
  stopped and put back at the head of its place in the queue, with its estimate raised to what it had reached. A
  sandbox job writes one file and is repeatable, so stopping one costs its time and nothing else, which is a better
  trade than the kernel's out-of-memory killer choosing for us. `memoryPreempt: false` turns it off.

**Being the one that is killed.** On Linux every sandbox child is started with a raised `oom_score_adj`, so that if the
kernel has to kill something it picks a sandbox and not the daemon -- whose death loses every warm context and every
request in flight. A sandbox that dies by `SIGKILL` (which `process_crash.describe_termination` already reads as
probably out of memory) is retried once, admitted alone.

**One failure is one failure.** `Project.render_async` gathers its pictures with `return_exceptions`, as
`_render_packages_async` already gathers packages, and raises the first failure once the rest are done. Today the
first exception ends the package's render, which is how one kill in the warm run cost eight pictures (section 2).
This one is a few lines and does not wait for the rest of the step.

**Saying why it waits.** A held-back job is silence on the wire, and a client gives up on a daemon that says nothing
for five minutes (`PC_DAEMON_IDLE_TIMEOUT`, `partcad_utils.timeouts`). While anything waits for memory, the admission
logs once a minute what it is waiting for and what is running ("castle-front.png waits for about 4.1 GB; 2.3 GB free;
running: castle.png, f1.png"), which keeps the client waiting and tells the user why the run is slower than the cores
would suggest.

**What it replaces.** The polled count in `ProcessSlots`. Waiters are woken in priority order (step 6) by the lease
that frees room, through `call_soon_threadsafe` on each waiter's own loop, so nothing polls.

## 10. Step 6: finish what is started

**A priority for every unit of work.** A tuple: the position of the work in the order a run with one slot would reach
it. The root of a command is `(0,)`; a fan-out site gives its *i*-th child its own key plus `(i,)`. Tuples compare
lexicographically, so a smaller key is earlier in the depth-first order -- the whole of the castle, every
sub-assembly, part and picture of it, sorts before anything of the car. The key lives in a context variable,
`scheduler.priority`, and is set at the fan-out sites that exist today:

- `Project.render_async` (each shape, then each file type of it), `Project.test_async` and the lint equivalents;
- `Assembly._get_shape_real` (each child, in declaration order);
- `_render_packages_async`, `_route_packages_async` and the test and lint walks in the daemon (each package);
- `Context` loading packages.

Until step 7 removes the thread hops, the key travels across them by hand: `sync_threads._Work` captures it beside the
OpenTelemetry context it already carries, and restores it on the thread that runs the work.

**Admission in that order.** `Admission`'s queue (step 5) is a heap on the key. The slot pools' FIFO `deque` becomes
the same heap, and the polled locks hand over in key order. The scheduler stays work-conserving: a lower key that
is not ready (waiting for a part) does not keep a free lease idle, and the next key that is ready takes it.

**Priority inheritance.** A shape used in two places is built once, by whoever asked first. If that was a late,
low-priority caller -- the alias `castle-front` asking for `castle/spire` -- an early caller waiting for the same build
lends it its key; otherwise a high-priority picture waits behind a low-priority build. Through the shape lock today,
through the single-flight future after step 7.

**What changes for `pc render -r` of the examples.** Today all 33 pictures start at once, every assembly tree is put
together in the daemon at once, and whichever of them polls first after a release gets the next sandbox. With a
priority, the castle's builds and its pictures take the leases first and finish first, the car's start as leases
free up, and at any moment the trees and requests held in the daemon are those of the few pictures that can actually
run. Admission in step 5 decides how many that is; this step decides which.

## 11. Step 7: one scheduler instead of the thread pools

Steps 5 and 6 put a memory bound and a priority on the one strict limit PartCAD has, the sandbox processes, and they
can be built on today's threading. This step is the refactor that makes those two the *only* mechanism, and it is
what retires the nested-wait deadlock as a class rather than case by case.

### 11.1 Why the pools have to go

Nothing in the daemon computes geometry. Every part, render, export, analysis and route is a sandbox process (or a
container exec), and the Python side of PartCAD only prepares requests and waits for answers. The two thread pools of
`sync_threads`, each thread running an `asyncio.run()` of its own, are left over from when factories built shapes
in-process. What they cost now:

- **The deadlock class.** A slot held by work that waits for other work: N waiters fill a pool of N and wait for a
  task that cannot get a slot. #834 (0.8.238) ended the known cases with three rules -- nested work runs on the
  caller's slot, a slot waiting for a lock gives itself back, a part goes to the pool before its lock is taken -- plus
  a 60 s backstop on waiting for another thread's preparation (`_PREPARE_WAIT_MAX`, `PreparationInFlight`). Each rule
  closes a path; none makes the class impossible, and each new way of nesting work has to be checked against all of
  them.
- **No limit that holds.** To stay deadlock-free a slot pool "runs over its size for as long as the wait lasts", with
  `_THREADS_UNBOUNDED` threads behind it. That is the right trade for a pool, and the reason a pool cannot be where a
  memory bound lives.
- **Polling.** `PoolAwareRLock`, `ProcessSlots`, `EnvironmentLock` and the preparation wait all poll (2 ms backing off
  to 50-100 ms), because they are taken from several event loops on several threads. Polling decides admission order
  by whoever wakes first.
- **Work that cannot be prioritised.** A priority has to follow the work across a thread hop by hand (an
  `asyncio.run()` on a pool thread starts from that thread's context, not the submitter's).

### 11.2 The model

- **One event loop per request**, as the daemon already has at the top of each request, and as `asyncio.run()` gives
  the synchronous library API at its entry points. Everything below it is coroutines.
- **Work is a tree of tasks** (structured concurrency). A fan-out site -- a package's shapes, an assembly's children,
  the packages of a recursive command -- starts its children through one helper, which gives each child its priority
  (section 10) and gathers them in order.
- **A join is an await.** A parent waiting for its children holds nothing: no thread, no slot. The deadlock of 11.1
  needs a waiter that holds a scarce resource, and the only scarce resource left is the sandbox lease, which is held
  only by a process that is running and never waits for another lease. That invariant is asserted (a launch from code
  holding a lease raises) rather than argued.
- **One admission point**, `scheduler.Admission` (steps 5 and 6), for every sandbox launch: Python, JavaScript,
  docker, remote, KiCad, container plugins. It replaces `ProcessSlots`, `ReentrantGate`, and the ad hoc semaphores
  (`at_once` in `_render_packages_async`, `_route_packages_async`, `_sandbox_budget` in `assembly_guide`, the one in
  `actions/package/install.py`).
- **Single-flight instead of shape locks.** Building a shape, or writing one of its files, is a future per (shape,
  operation): the first caller starts it, the others await it and lend it their priority. Across threads (the daemon's
  `--http` transport serves requests concurrently) it is a `concurrent.futures.Future` awaited with
  `asyncio.wrap_future`, so nothing polls. A preparation is the same kind of future, which removes the preparation
  wait and its backstop.
- **Blocking calls are offloaded**, to a small plain `ThreadPoolExecutor`: a git operation, hashing a large file,
  compressing or JSON-encoding a large payload, reading an ASSY file. Offloaded code may not await the scheduler
  (enforced with a thread-local), so offloading cannot recreate the deadlock.

### 11.3 Work stealing, or depth-first priority

The properties asked for are three: a parent waiting for its children must never be what stops them; work already
started is finished before new work fans out; and how much runs at once follows memory. Work stealing (Cilk, TBB,
Java's ForkJoin, Tokio) gets the first two with per-worker deques: a worker runs its own newest task (depth-first), an
idle worker steals the oldest task of another (breadth where it is free), and a worker that joins runs other work
instead of blocking.

Here a join already releases the worker, because it is an await, and the GIL means extra Python threads add no
throughput to work that only waits. What remains of work stealing is its *order*. **Parallel depth-first** scheduling
-- run ready work in the order a run with one slot would reach it, and use the other slots for what comes next in that
order -- gives the same "finish what is started" behaviour with a tighter memory bound: about S1 + P x D for P slots
and a tree of depth D, against P x S1 for work stealing (Blelloch, Gibbons and Matias, 1999; Blumofe and Leiserson,
1999). Memory is the reason for the change, so that is what this proposes: a priority queue keyed by position in the
serial order (section 10), with no per-thread deques. If in-process CPU work ever comes back, a work-stealing executor
can sit behind `offload()` without changing anything above it.

### 11.4 Migration

Each item is a pull request with the suite green, and the order keeps every intermediate state shippable:

1. `src/partcad/scheduler.py`: priority, `Admission`, `offload()`, single-flight. At first it wraps today's pieces, so
   steps 5 and 6 land on it.
2. Parts and sketches built on the request's loop (`built_on_pool = False` throughout); `Assembly.instantiate()` and
   the other synchronous factory bodies through `offload()`. The constrained pool goes unused.
3. `Shape.locked()` becomes single-flight per (shape, operation) plus an `asyncio` lock per output path.
4. The places that run a coroutine to completion from synchronous code inside a running loop
   (`threadpool_manager.complete`, `project_external_repository`, and the rest of the ~75 `asyncio.run()` call sites
   that can be reached from a loop) are made coroutines. A debug check raises on `asyncio.run()` from a thread whose
   loop is running.
5. `ReentrantGate` and the per-call semaphores go, replaced by priority children under `Admission`.
6. `SlotPool`, `PoolAwareRLock`, the slot give-back and `sync_threads` are deleted. The tests that hold today's
   guarantees -- `test_sync_threads.py` and `test_nested_build.py`, which run pools of one and two -- are kept and
   re-pointed at an `Admission` of one and two leases.

`docs/source/features.rst` says threads are raised to four "for performance" and that the pools keep the daemon's
size; both paragraphs change with step 6 of this list.

## 12. The example repository and the parts library

**partcad-ldraw-examples.** Its CI job carries two workarounds for this problem, and both comments have gone stale:

- `threadsMax: 3`, with "Three is the fewest it works with: with two, a render waits on itself and never finishes."
  Since 0.8.238 (#834) the floor is four and a lower value is raised to it with a warning, so the job already runs four
  sandboxes at once; and nested waits no longer deadlock at any size. The value does nothing today. Once step 5 is
  released it should go, because memory, not a guess at a count, then decides how many drawings run together.
- An 8 GB swap file, "Paging is slower than having the memory, and much better than the kernel killing a drawing".
  That stays: it is exactly what the `Swap` healthcheck will recommend.

Nothing in the repository has to change for steps 1 to 4. The `partcad: ">=0.8.191"` floor would rise to the release
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

## 13. Validation

- **The measurement is repeatable.** The three scripts behind section 2 -- a sampler of every PartCAD process's
  memory, a driver that captures the exact request the daemon sends a render sandbox, and a harness that replays it
  phase by phase -- go into `dev-tools/profiling/` with the first pull request, and every later one quotes their
  before-and-after numbers for the examples.
- **The policy is unit-tested without a machine to fill.** `Admission` takes its memory probe and its process sampler
  as parameters, so the tests drive it with scripted numbers: admission in priority order; the progress guarantee (one
  job bigger than the budget still runs, alone); the watermarks; preemption of the lowest-priority job and its
  requeue; a lowered `threadsMax` or `memoryMax` while leases are held; and the log line that keeps a client waiting.
- **The deadlock guarantees are kept.** `test_sync_threads.py` and `test_nested_build.py` run against an `Admission`
  of one and two leases, plus a test that a sandbox launch from code holding a lease raises.
- **End to end.** `pc render -r` of partcad-ldraw-examples, default configuration, completes on a 16 GB machine with
  no swap, with the peak under the budget; and it completes -- slower -- inside an 8 GB cgroup, where today it is
  killed. The second runs in CI as a `docker run --memory=8g` job when the change touches `sandbox_lock`,
  `scheduler` or the render wrappers; it is too slow for every pull request.
- **Pictures.** Nothing here may change an exact (`reproducible: true`) picture, and `Examples (PartCAD)` fails if
  one does. A polygonal one may change once, by the tie-breaking 5.1 describes, and the pull request that changes it
  re-renders it and says so -- `castle-front.png` in partcad-ldraw-examples, measured at 39 pixels.

## 14. Open questions

1. **Sharing geometry in the sandbox** (5.1) makes every placement of a part the same OCCT shape. No built-in
   implementation modifies what it is handed; an implementation published by another package might. Is "do not
   modify the shapes you are handed" acceptable as a stated rule of the implementation contract, or should sharing be
   something an implementation opts into?
2. **Preemption** (step 5). Stopping and re-queuing the lowest-priority job under a critical watermark: on by
   default, or opt-in?
3. **The reserve.** The larger of 1 GB and a tenth of the budget, or something else?
4. **Depth-first priority instead of work stealing** (11.3). The reasoning is that a join here is already an await,
   so what is left to choose is the order, and depth-first order has the better memory bound. Agreed?
5. **Caching pictures** (step 3). With it, `pc render` can write a file without running anything. Default on, as the
   shape cache is, or behind a setting?
6. **Where the learnt peaks live** (step 5). A small entry in the shape cache keyed like the shape (shared through
   the remote tiers with everything else, so CI learns from developers and the other way round), or a local file
   beside the cache that is never shared?
