# Memory and scheduling: design

This is the design record for how PartCAD spends a machine's memory on a large design, and how it decides what to run
next. It starts from a measurement -- `pc render -r` of
[partcad-ldraw-examples](https://github.com/partcad/partcad-ldraw-examples) on a 16 GB machine -- and ends in a plan.
How to *use* any of it is the user documentation's job; this file is for whoever changes it.

Status words used below: **built** is on `devel`; **decided** is agreed and not built; **open** is not agreed.

Where it stands: step 1 is **built** (#849, which added this record). Step 3 is **built** as part of #848, which
caches every export and render; step 2 is #850, which drops its own picture cache in #848's favour. Step 4 is being
done separately. Steps 5 to 7 are **decided** (section 9) and implemented on top of #850, measured in 11.1; what the
measurements leave open is in section 12.

## Contents

1. [The problem](#1-the-problem)
2. [What was measured](#2-what-was-measured)
3. [Where the memory goes](#3-where-the-memory-goes)
4. [The plan at a glance](#4-the-plan-at-a-glance)
5. [Step 1: release and share in the sandbox](#5-step-1-release-and-share-in-the-sandbox)
6. [Step 2: the daemon and the wire](#6-step-2-the-daemon-and-the-wire)
7. [Step 3: the disk cache](#7-step-3-the-disk-cache)
8. [Step 4: the swap healthcheck](#8-step-4-the-swap-healthcheck)
9. [Steps 5 to 7: admission by memory](#9-steps-5-to-7-admission-by-memory)
10. [The example repository and the parts library](#10-the-example-repository-and-the-parts-library)
11. [Validation](#11-validation)
12. [Open questions](#12-open-questions)

## 1. The problem

`pc render -r` of partcad-ldraw-examples -- a 731-part castle and a Technic car of 236 placed parts (237 pieces in its
README's shopping list), built from the LDraw library, and 33 pictures of them and of their sub-assemblies -- runs out
of memory on a machine with 16 GB or less. That repository's CI runs it with an 8 GB swap file added for the purpose,
and with a `threadsMax` it believes keeps three drawings at once (and which has been raised to four since 0.8.238).

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
| 5-7 | Admission by memory | `sandbox_lock.py`, `cache_shape.py`, `shape.py`, `project.py`, `sync_threads.py`, `runtime.py` | every core busy, started work first, no new task past the daemon's budget except the best-ranked one when nothing runs; nothing running touched; idle objects freed on demand | decided: section 9 |

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
`decode_tree` and `decode_shape`. `wrapper_interference.py` still decodes per node, on purpose: it takes booleans
between placements, and between two placements of one `TShape` that is a change of its own to make. What has to be
checked is that no implementation modifies a shape it was handed in place, since a change to one placement would now
be a change to all of them: the built-in exporters write files from the shapes and modify none;
`cae_support.prepare()` imprints sketches on a *part*, which has one placement. The key is the payload string as it
arrived, so two different geometries are never confused; hashing it is not needed in the sandbox.

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
- Not done here: the memory tier keeps every entry under 100 MB for the life of the context, and a warm daemon never
  drops a context (the TODO in `core/session.py`). Freeing idle objects on demand, least recently used first, with
  `Shape._wrapped` let go along with its entry, is what bounds what a long-lived daemon accumulates; it changes the
  lifetime of every shape a context holds, and is part of steps 5 to 7 (section 9, point 9).

## 7. Step 3: the disk cache

### 7.1 Cache the pictures

#848 caches every export and render -- exports too, with the files an exporter reports writing beside the one it was
asked for (`output.FILES_KEY`), which is what the paragraphs below left exports out for. It covers this step and more;
#850 drops its own picture cache once #848 is in.

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
base64. The castle's entry fits easily; `f1`'s distinct geometry alone is 10.9 MB of compressed BREP, so it does not fit
the 10 MB limit. **Decided:** the default `cacheFilesMaxEntrySize` becomes 50 MB, which `f1` fits; an entry that
names its parts' own cache entries instead of carrying them stays the remedy for a tree bigger than that. An earlier
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

## 9. Steps 5 to 7: admission by memory

Two proposals for these steps have been withdrawn: a budget held below RAM, which held cores back long before memory
ran out, and then pausing or stopping running tasks at a margin short of capacity. A third, charging each task the
peak it is expected to reach, is withdrawn too. What is **decided**:

1. **Every core stays busy while memory allows.** As many sandbox processes run as there are slots (`threadsMax`)
   while there is work for them, as today.
2. **What is started is finished first.** While the castle occupies only a few cores, the car's tasks use the rest.
   When the castle fans out into more tasks, new starts go to the castle, and the number of car tasks in flight falls,
   to none if need be.
3. **The budget is a share of this machine's capacity, and each daemon budgets for itself.** Capacity is RAM plus
   swap (or page file), and the swap is counted by default (`memoryBudgetSwap: true`; `false` leaves it out). The
   share is `memoryBudget`, 0.8 by default. Other daemons and other processes are not accounted for: where they need
   memory too, the administrator lowers the share. A remote renderer is a machine dedicated to rendering, and budgets
   the same way on its own side; the daemon that sends it work does not count that work against its own budget.
4. **Nothing running is touched.** No task is paused, frozen, stopped or made to wait once it has started. The one
   lever is not starting new tasks until memory conditions improve.
5. **Nothing is anticipated.** No task is assumed to need any particular amount of memory, recorded or estimated. A
   task starts while the daemon's usage is under the budget, and a started task may -- will -- overshoot: the 20% the
   budget leaves is the room for that. The burst at the start of a run, when every slot fills while usage is still
   near nothing, is accepted for the same reason.
6. **Nothing is throttled to a stop.** Whenever no task is running, the best-ranked waiting one starts, whatever the
   usage -- with a warning when usage is over the budget. Every running task ends, so a design bigger than the machine
   is slowed down to one task at a time, and then fails or finishes; it never stops.
7. **A task is one wrapper call, or one load in the daemon.** Not a process -- a container serves many calls, and a
   call may start more than one -- and not an action, which may hold many tasks. Every call into a sandbox, an
   implementation's container or a container sandbox is one task. So is each object the daemon reads into memory from
   a cache tier: putting a large assembly together is many tasks, one per object it reads, and can be held back
   between any two of them. (A client asking for one assembly already makes that many requests, one per sub-assembly,
   through `partcad_utils.staging`; a recursive render makes one, and the tasks are what divides it.)
8. **An object is built once and then drawn in every way it is asked for.** One copy of its geometry is in memory
   while its pictures and exports are produced, one by one or in parallel where the budget allows -- not one tree per
   picture -- and then it is released.
9. **Finishing work frees memory.** A sandbox frees everything when its process exits. In the daemon, an object no
   longer used is either dropped, when a disk tier holds it and it is over 1 MB (`cacheMemoryDoubleCacheMaxEntrySize`)
   -- which is what happens today -- or kept on one of **two least-recently-used lists**: one for the large objects no
   persistent tier holds (most of them over the file tier's limit) and one for objects under 1 MB. When usage reaches
   **90% of the budget**, idle objects are freed: from the list of large ones first, then the small ones, the least
   recently used first in each, until usage is back under that mark or both lists are empty.
10. **The memory tier keeps entries up to 250 MB** (`cacheMemoryMaxEntrySize`, 100 MB today), so that the large list
    has a range of sizes to hold -- 50 to 250 MB -- and the file tier takes entries up to 50 MB (7.2).
11. **Usage is what Python cannot reuse.** Memory a process has freed is not always given back to the system: the
    allocator keeps it for the next allocation. Freeing runs the garbage collector, gives back what the allocator can
    give back, and counts what it keeps -- free blocks and pools in Python's own allocator, free chunks in C's -- as
    available rather than used, since the daemon's next load reuses it. Without that, the daemon frees and its usage
    does not fall, and admission does not resume.

The design that carries it out, **decided** with the points above and built in the pull request that implements them:

- **Admission sits where every task already starts.** A wrapper call takes a process slot
  (`sandbox_lock.process_slots`) and a load takes none; both are admitted by the one controller behind the slots. A
  call into a container endpoint takes a slot now too: in docker's `upload` mode and for every implementation's
  container it took none, so a recursive render fanned out into the container without a bound. The remote sandbox's
  calls are admitted on the remote side (point 3). The coroutines and threads that wait for tasks are not tasks.
- **The admission rule is one comparison.** A waiting task starts when it is the best-ranked of the waiters that can
  use what is free -- a slot for a call, nothing for a load -- and the daemon's usage is under the budget; or, under
  point 6, when nothing is running at all. Admitted tasks never wait for anything, which is what makes "nothing
  running" a state the daemon always reaches.
- **Usage is this daemon's own footprint**: its own process less what its allocators hold for reuse (point 11), the
  processes it started, and the containers it runs work in (their memory less the file cache, as `docker stats`
  reports it). A process counts with the memory it holds of its own -- on Linux its anonymous pages (`RssAnon` and
  `RssShmem`), on Windows its private bytes, RSS elsewhere -- which is where geometry lives. PSS was the first choice,
  and was measured out of it: reading it walks a process's page tables, 24 ms for a 3 GB sandbox, so four of them
  twice a second is a tenth of a core; this is microseconds. What it leaves out is the libraries mapped from files,
  which the sandboxes share and the page cache holds once, and the share absorbs them. **Capacity** is RAM, plus
  swap by default, or a cgroup's `memory.max` (plus `memory.swap.max`) where that is smaller. Under a cgroup limit
  the kernel charges more than the footprint -- page cache, kernel memory, every other process in the cgroup -- and
  the share is what absorbs that, as it absorbs other processes on an ordinary machine. On macOS swap has no fixed
  size; there the swap counted is what is allocated at the moment. Measured twice a second while anything runs or
  waits, and again after freeing.
- **Freed memory is given back to the system where it can be.** glibc raises its `mmap` threshold each time a large
  block is freed, up to 32 MB, so later blocks of that size come from the heap and stay in the process after they are
  freed. The daemon fixes the threshold (`M_MMAP_THRESHOLD`), so a payload is unmapped as soon as it is freed, and
  calls `malloc_trim(0)` after freeing idle objects.
- **Order: objects, then first come first served.** For `pc render -r` and `pc export -r` the unit ranked is the
  object, with all of its pictures and exports (point 8). Objects rank by when their first task started, objects not
  started yet by declaration order; within an object, tasks are taken in the order they asked. A task building
  something that a better-ranked task waits for -- a brick two pictures need -- ranks as the better of the two: a
  shape being built carries the rank of the best of those waiting for it. The rank travels with work across a thread
  hop, beside the OpenTelemetry context `sync_threads._Work` already carries. Today's pools stay: since #834 they are
  deadlock-free at any size.
- **An object's outputs share its one copy.** `Project.render_async` gathers its objects' outputs together, so that
  the views of one model -- `f1` and its three views -- are produced from the one tree in memory while any of them
  runs. An object over 1 MB that the file tier holds is kept while anything uses it (point 8), and dropped when nothing
  does, rather than read again by each of its outputs.
- **The two idle lists live in the memory tier** (`cache_shape.ShapeCache`), over what `Shape._wrapped` holds. An
  object is in use while anything other than the memory tier holds its tree, which needs no bookkeeping from the
  callers of `get_wrapped`; an idle one is on its list, most recently used last. An entry's recorded size is only a
  guess at what freeing it returns, since entries share payloads (#849, #850); what counts is the usage measured
  afterwards. Only what the memory tier was given is ever freed: a part made from a live shape has nothing to be
  built again from.
- **The sandbox's own release** (5.2) is worth doing now: the less a task overshoots, the less of the 20% it uses.
- **The client keeps waiting.** A task held back by memory says so in the log, and goes on saying so every thirty
  seconds, so the client's 300 s idle timeout (`partcad_utils.timeouts`) does not fire; and time spent waiting to be
  admitted does not count against a task's own timeout, which starts with its process.
- **A failed task is one failure.** `Project.render_async` gathers a package's pictures with `return_exceptions`, as
  `_render_packages_async` already gathers packages, and raises the first failure once the rest are done: the first
  exception used to end the package's render, which is how one kill in the warm run cost eight pictures (section 2).

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
- **Scheduling is unit-tested without a machine to fill**, once it exists: the admission and the memory tier take
  their memory probe as a parameter, so tests drive them with scripted numbers -- rank order with spare slots; a
  fan-out taking new starts from a later object without touching its running tasks; no start over the budget, and
  starts resuming as tasks end and the daemon frees; the large idle objects freed before the small ones; the progress
  guarantee. `test_sync_threads.py` and `test_nested_build.py` keep holding the pools to being deadlock-free at sizes
  one and two.
- **End to end.** `pc render -r` of partcad-ldraw-examples, default configuration, completes on a 16 GB machine with
  no swap -- which it does with step 1 -- and, once admission is built, inside an 8 GB cgroup, where today it is
  killed; and the daemon's usage falls between roots.
- **Pictures.** Nothing here may change an exact (`reproducible: true`) picture, and `Examples (PartCAD)` fails if
  one does. A polygonal one may change once, by the tie-breaking 5.1 describes, and the pull request that changes it
  re-renders it and says so -- `castle-front.png` in partcad-ldraw-examples, measured at 39 pixels.

### 11.1 Measured with admission

`pc render -r` of partcad-ldraw-examples (`8bc2963`) on the machine of section 2, inside memory cgroups of the sizes
given, no swap, default configuration (four sandbox processes; `memoryBudget` 0.8). Warm means the shape cache is
warm and the pictures are not cached (#848 would otherwise draw nothing); cold means neither is, so every LDraw part
is built from its `.dat` file. "#850" is that pull request, the base this is built on; "admission" is steps 5 to 7.
Peaks are the sum of every PartCAD process's PSS, sampled once a second (`dev-tools/profiling`).

| run | limit | build | pictures | time | peak | daemon peak |
| --- | --- | --- | --- | --- | --- | --- |
| warm | 14.3 GB | #850 | 33 of 33 | 253 s | 8.1 GB | 393 MB |
| warm | 14.3 GB | admission | 33 of 33 | 258 s | 6.8 GB | 219 MB |
| warm | 8 GB | #850 | 33 of 33 | 232 s | 7.5 GB | 380 MB |
| warm | 8 GB | admission | 33 of 33 | 230 s | 7.4 GB | 278 MB |
| cold | 8 GB | #850 | 33 of 33 | 976 s | 7.8 GB | 384 MB |
| cold | 8 GB | admission | 33 of 33 | 980 s | 6.7 GB | 291 MB |
| warm | 6 GB | #850 | 24 of 33: a kill at 116 s ends the render | -- | 6.4 GB | 357 MB |
| warm | 6 GB | admission | 31 and 29 of 33, in two runs | 207-217 s | 6.4 GB | 276 MB |
| warm | 6 GB, `memoryBudget: 0.5` | admission | 32 of 33, in two runs | 273-281 s | 6.4 GB | 211 MB |
| warm | 6 GB | admission, starts paced (12) | 33 of 33 | 298 s | 6.2 GB | 230 MB |
| warm | 14.3 GB | admission, starts paced (12) | 33 of 33 | 307 s | 6.5 GB | 196 MB |

What it shows:

- **Steps 1 and 2 are what moved the line.** With them, the warm and the cold run both fit 8 GB without admission;
  admission costs nothing measurable there (230 s against 232 s, 980 s against 976 s), takes the peak down by up
  to 1.3 GB, and the daemon's by a quarter to nearly half.
- **Nothing stops.** Every run with admission started all 33 drawings, and a killed drawing cost that drawing alone
  (`return_exceptions`); without it the first kill ended the render with nine pictures not drawn.
- **Admission holds tasks back** -- "14 task(s) wait for memory to start: PartCAD's work holds 5.3 GB of its 4.8 GB
  budget" -- **but at 6 GB it cannot keep the OOM killer away.** A drawing of the F1 or of its larger parts grows by
  1.2 to 2.5 GB after it starts, more than the 1.2 GB the share leaves, so one started at 4.5 GB goes past 6 GB.
  Halving the share does not help either: the four views of the F1 wait for one tree, become ready together with
  nothing else running, and all four start at 1.9 GB of usage, as in section 2. Nothing anticipated means exactly
  this, and section 12 has the question it leaves.
- **A defect the 6 GB runs found and that is fixed:** the monitor forgot its measurement whenever nothing ran, if only
  between two objects, and the next waiters all started as if the run were just beginning.

## 12. Open questions

The four questions of the previous round are answered in section 9: freeing starts at 90% of the budget (point 9),
the swap is counted by default (point 3), the memory tier's limit becomes 250 MB (point 10), and the burst at the start
of a run is accepted (point 5), with every wrapper call and every load a task of its own (point 7). The measurements
(11.1) leave one:

1. **Bursts in the middle of a run.** The burst accepted at the start of a run happens in the middle of one too:
   whenever several tasks become ready while little runs -- the views of one model, waiting for its one tree -- they
   fill every free slot at once, and each then grows by up to 2.5 GB. Measured usage cannot see that coming, and the
   share's margin absorbs it only where it is bigger than the growth of every task that can start together: a 16 GB
   machine, and 8 GB for these examples. A rule that guesses nothing about any task closes it at 6 GB (11.1): **a
   task starts only once the memory has stopped rising since the last one did** -- usage flat over two seconds of
   measurements, the last start at least two seconds back -- with the usual exception when nothing runs. It costs a
   fifth of the time on a machine with room to spare (307 s against 258 s), because every start waits for the one
   before it to settle. Adopt it, always or only below some machine size; or keep the decided rule and leave small
   machines to `memoryBudget` and swap?
