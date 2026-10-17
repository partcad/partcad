#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Preparing a shape once, however many callers ask for it at the same time.

A shape is prepared before anything reads its cache key (see
'Shape.prepare_async'): its files are fetched and the objects it is made of are
resolved, and each of those adds its own key to the shape's. Only once the last
of them has is the key the shape's key. Reading it earlier finalizes a partial
one - and does worse than that, because the first read also hashes the files the
shape depends on, so everything added after it lands behind them and the key
the shape ends up with is not the one a preparation run alone produces.

Preparing used to be guarded by a flag raised before the work started, which
kept a shape that links back to itself from recursing but also turned away
every *concurrent* caller, as if the work were done. Two renders of one
assembly, an alias of it, or two assemblies sharing a sub-assembly were enough:
the second caller read the key half way through the first one's preparation.
'Hash update after being used' was the symptom, logged for every key added
after that read - and the cost was an assembly cached under a key that depended
on timing, rebuilt by every run that happened to compute a different one, and
an offset alias keyed on whatever part of its source's key existed when it
looked.

So a caller now waits for a preparation in progress, and only one that is part
of that very preparation - a reference cycle, the case the flag was for - is
let through without it. "Part of it" is said by a context variable, which
follows the preparation down through every object it awaits and into every task
it starts; and two preparations each waiting on a shape the other is preparing
are a cycle too, found by following who waits for whom, and let through the
same way. Waiting is polling, like the sandbox locks, because the callers can
be on different event loops in different threads.
"""

import asyncio
import contextvars
import threading

# How long a waiting caller sleeps between looks, in seconds: a preparation is
# file downloads and package loads, so the upper bound costs nothing next to
# it, and the lower one keeps a short wait short.
_POLL_MIN = 0.001
_POLL_MAX = 0.05


class _Chain:
    """One preparation and everything it prepares on the way, as a single party.

    The identity is all there is to it: a shape this chain is preparing is one
    it may not wait for, because the wait would be on itself.
    """

    __slots__ = ("__weakref__",)


# The chain the running code belongs to, if it is preparing anything.
_current = contextvars.ContextVar("partcad_preparation_chain", default=None)

_guard = threading.Lock()
# The chain preparing each shape, by 'id()': present for exactly as long as
# the shape's preparation runs, during which the chain holds the shape.
_preparer = {}
# The shape each waiting chain is waiting for, by 'id()'.
_waiting_for = {}


def _waits_for_chain(owner, chain) -> bool:
    """Whether 'owner' is, through whatever it waits for, waiting for 'chain'.

    Called with '_guard' held. A wait that would close such a circle is a
    reference cycle split across two preparations, and would never end.
    """
    seen = set()
    while owner is not None and owner not in seen:
        if owner is chain:
            return True
        seen.add(owner)
        shape_id = _waiting_for.get(owner)
        if shape_id is None:
            return False
        owner = _preparer.get(shape_id)
    return False


async def prepare(shape, hook) -> None:
    """Run 'hook(shape)' to prepare 'shape', unless it is prepared or being prepared.

    Returns once 'shape._prepared' is true, having run the hook if nobody else
    was; waits for a caller that is running it; and returns at once to a caller
    that is part of that preparation itself (see the module's docstring), which
    is what keeps a reference cycle from waiting on itself. A hook that raises
    leaves the shape unprepared, and a caller that was waiting for it then runs
    it again, and is the one told how it failed.
    """
    chain = _current.get()
    while True:
        with _guard:
            if shape._prepared:
                return
            owner = _preparer.get(id(shape))
            if owner is None:
                if chain is None:
                    chain = _Chain()
                _preparer[id(shape)] = chain
                break
            if chain is not None and (owner is chain or _waits_for_chain(owner, chain)):
                return
            if chain is None:
                chain = _Chain()
            _waiting_for[chain] = id(shape)
        try:
            delay = _POLL_MIN
            while True:
                await asyncio.sleep(delay)
                with _guard:
                    if _preparer.get(id(shape)) is not owner:
                        break
                delay = min(delay * 2, _POLL_MAX)
        finally:
            with _guard:
                _waiting_for.pop(chain, None)

    token = _current.set(chain)
    prepared = False
    try:
        if hook is not None:
            await hook(shape)
        prepared = True
    finally:
        _current.reset(token)
        with _guard:
            # Raised before this preparation stops being the one in progress,
            # so that a waiter finds one or the other and never neither.
            if prepared:
                shape._prepared = True
            del _preparer[id(shape)]
