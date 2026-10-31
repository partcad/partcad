.. _threads-max:

#################
Machine Resources
#################


``threadsMax`` says how much of the machine PartCAD may use:

  .. code-block:: yaml

    # ~/.partcad/config.yaml
    threadsMax: 8

The equivalents everywhere else are ``PC_THREADS_MAX`` in the environment and
``--threads-max`` on the command line, in the usual order of precedence. It
sizes two things:

* **How many sandbox processes run at once.** This is the limit that is strict,
  and the one that matters: every script PartCAD runs is a whole CAD
  interpreter, several hundred megabytes of it, so it is the number of these and
  not the number of threads that decides whether a recursive render keeps the
  machine busy or runs it out of memory.
* **The thread pools** PartCAD's own work runs on. Not a strict limit.

**It is never lower than 4.** A lower value, from any of those places, is raised
to 4, and PartCAD says so::

    threadsMax 2 (from PC_THREADS_MAX) is below the minimum of 4; using 4 instead

Four is the least PartCAD runs with, for performance: a recursive render starts
every object of a package at once and spends most of its time waiting for
sandbox processes, so it is how many of those run side by side that decides how
long it takes.

It used to be the least PartCAD *could* run with. ``pc render -r`` once stopped
making progress altogether with ``threadsMax: 2``: an object built from another
one -- an alias, an enrich, an extrusion of a sketch -- held a thread of the
pool while it waited for a second one to build the other object on, and a
recursive render started enough of them at once for every thread to end up
waiting. Nothing waits like that any more: an object built from another one
builds it on the thread it already has, on a pool of any size. A lower value
would no longer stop anything; it is raised to four all the same.

When nothing sets it, PartCAD runs one sandbox process per CPU core -- and still
never fewer than four, so on a machine with fewer cores than that it notes, once::

    PartCAD needs at least 4 CPU cores for optimal performance, and found 2

Everything still works on such a machine, more slowly. The note is information
rather than a warning, since nothing about the command it comes with can change
it; ``pc healthcheck`` reports the same thing as a warning, in its ``CpuCores``
check. The cores counted are the ones
the machine has, not the ones a CPU affinity mask or a container's CPU quota
leaves to PartCAD; set ``threadsMax`` where those are smaller.

A command served by the daemon runs with **your** ``threadsMax``, not with the
one the daemon was started with: it travels with the rest of your configuration
on every request, and the daemon sizes its sandbox processes for each request it
serves. So ``PC_THREADS_MAX=6 pc render -r`` runs six at a time even on a daemon
that has been running since before the variable was set. The thread pools are
the exception: they belong to the daemon's process, and keep the size it started
with.
