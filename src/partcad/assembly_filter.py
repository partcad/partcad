#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A view of an assembly: some of what it holds, where it holds it.

Two things in PartCAD show part of an assembly rather than the whole of it, and
both show it as an *assembly*:

  * an assembly instruction book, whose every step pulls one item away from what
    the steps before it have put together -- "the sub-assembly so far" is the
    items placed up to that point, and nothing else (see assembly_guide.py);
  * ``pc render --filter`` and ``pc export --filter``, which keep the links a
    mask names and drop the rest, so that a drawing can be of one sub-assembly
    of a machine without a second declaration for it.

What they have in common is `derive`: an 'Assembly' whose children are handed
over rather than read out of a declaration. Everything that works on an assembly
then works on it -- it renders, it exports, it has a bill of materials, it draws
in the viewer -- because it *is* one, and because the items in it are the very
items the source placed, in the very places the source put them. A filter never
re-resolves a ``connect:``: what is kept stays where the assembly as a whole put
it, which is the only reading of "part of this assembly" that is true of the
machine on the bench.

A derived assembly is never cached. Its identity is "that assembly, minus these
links", which no declaration states and no cache key covers, so an entry written
under the source's name would be handed back the next time the *whole* object
was asked for. The objects inside it are cached as they always were, and
composing them again costs nothing but the composition.

The mask itself -- what a filter is, how it is written and what naming a link
means -- is `partcad_utils.assy_filter`, which is also what ``pc filter`` reads
to rewrite an ASSY file. One set of rules, read here for an assembly that has
been built and there for the file it was built from, so that a filtered render
and a filtered copy of the file hold the same parts.

A link is addressed by 'Assembly.link_name' -- its own name, or its position in
the assembly -- so there is no such thing here as a child a mask cannot name.
That is what lets this filter an assembly PartCAD did not read from an ASSY file
at all: a STEP assembly whose reader named nothing still has 'link#1',
'link#2', and so does an assembly put together in Python with 'add()'.
"""

from . import logging as pc_logging
from . import telemetry
from .assembly import Assembly, AssemblyChild


def derive(source, children, name=None, config=None):
    """An assembly holding exactly ``children``, built here rather than read.

    ``source`` is the assembly this is a view of: it supplies the kind of object
    to make (a scene's view is a scene), the package it belongs to, and -- unless
    ``config`` says otherwise -- its declaration, so that the view is configured,
    named and placed exactly as the thing it is a view of. That is what makes a
    filtered render land in the file the unfiltered one would have landed in, and
    what keeps the file types the package declared for the object applying to it.

    ``children`` are 'AssemblyChild' objects and are taken as they are, their
    placements and their connection records included. ``name`` overrides the
    name for a view that is not the object (a step of an instruction book is
    not), and ``config`` replaces the declaration for a view that should inherit
    nothing from it.

    Never cacheable; see the note at the top of this file.
    """
    cfg = dict(source.config if config is None else config)
    if name is not None:
        cfg["name"] = name
    cfg.setdefault("name", source.name)
    cfg["cache"] = False

    item = type(source)(source.project_name, cfg)
    # Nothing instantiates this one: its children are put in here, once, and
    # there is no file to read them back from. 'Assembly.do_instantiate()' finds
    # them already there and returns, which is what keeps the two from racing.
    item.instantiate = lambda _: True
    item.children.extend(children)
    item._wrapped = None
    return item


def _recast(child: AssemblyChild, item, name=None) -> AssemblyChild:
    """``child``, placing ``item`` instead of what it placed.

    Everything else about the child belongs to the node that placed it rather
    than to the object it placed -- where it sits, what it was connected to,
    what the file says it is -- and a filtered sub-assembly sits where the whole
    one sat.

    ``name`` pins what the assembly addressed it by. A child nothing named is
    addressed by its position ('Assembly.link_name'), and a view holds a subset,
    so a position would rename it on the way in: the second child of five is the
    first of two. Writing it down keeps the view's labels the ones the panel was
    showing when the filter was composed.
    """
    return AssemblyChild(
        item,
        child.name if name is None else name,
        child.location,
        child.comment,
        child.how,
        child.connection,
        child.description,
        child.located,
    )


@telemetry.instrument_function_async("assembly_filter.filtered")
async def filtered_async(assembly, mask, where: str = "the filter"):
    """``assembly`` with only the links ``mask`` keeps, as an assembly of its own.

    ``None`` as the mask is no filter at all and the assembly itself comes back,
    so a caller need not branch on whether one was asked for. What the mask asks
    for and the tree cannot give is reported through the log, naming the link:
    a filter is how somebody says what they want to look at, and a name that
    selects nothing is a question that was never answered.
    """
    if mask is None or mask.keeps_all:
        return assembly

    await assembly.do_instantiate()
    problems: list = []
    kept = await _filter_children(assembly, mask, where, problems)
    for problem in problems:
        pc_logging.error("%s:%s: %s" % (assembly.project_name, assembly.name, problem))
    if not kept:
        pc_logging.error(
            "%s:%s: the filter keeps none of its links: %s"
            % (assembly.project_name, assembly.name, ", ".join("'%s'" % name for name in mask.names()))
        )
    return derive(assembly, kept)


async def _filter_children(assembly, mask, where: str, problems: list) -> list:
    """The children of ``assembly`` that ``mask`` keeps, in declaration order.

    Every child has a name this assembly addresses it by -- its own, or its
    position in the assembly ('Assembly.link_name') -- so this is a lookup per
    child. That name is also the label the child's node carries into the tree
    (see 'Assembly._child_name_label'), which is what lets the IDE compose a
    mask out of the rows it is showing.
    """
    if mask.keeps_all:
        return list(assembly.children)

    kept = []
    used = set()
    for index, child in enumerate(assembly.children):
        name = assembly.link_name(index)
        sub = mask.select(name)
        if sub is None:
            continue
        used.add(name)
        if sub.keeps_all:
            kept.append(_recast(child, child.item, name))
            continue

        if isinstance(child.item, Assembly):
            await child.item.do_instantiate()
            inner = await _filter_children(child.item, sub, "%s: '%s'" % (where, name), problems)
            if not inner:
                problems.append(
                    "%s: '%s' keeps none of its links: %s"
                    % (where, name, ", ".join("'%s'" % one for one in sub.names()))
                )
            kept.append(_recast(child, derive(child.item, inner), name))
            continue

        # A part is one shape and has no links inside it to select from.
        problems.append("%s: '%s' is a part, so there is nothing inside it to select; it is kept whole" % (where, name))
        kept.append(_recast(child, child.item, name))

    for name in mask.names():
        if name not in used:
            problems.append("%s: there is no link called '%s' here" % (where, name))
    return kept
