#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from partcad_utils import assy_filter

from ..assembly import Assembly
from .test import Test

# The floor that separates a boolean's arithmetic noise from a real overlap.
# Two touching surfaces should answer zero and answer a sliver instead; this is
# above that and far below anything anyone would call an interference.
DEFAULT_MIN_VOLUME = 0.05


class InterferenceTest(Test):
    """Fail an assembly whose parts share space.

    The 'cad' test passes an assembly whose parts are all in the wrong place -
    it only asks whether the geometry instantiates. This asks where the parts
    ended up, which is the question an assembly is actually judged on, and the
    one nothing has been able to answer without a person looking at a render.

    The answer comes from a boolean common and the volume of what it produces.
    Bounding boxes are not enough: two boxes meeting says very little about two
    solids - a bracket around a shaft, an L around a corner, anything rotated -
    so they are used only to choose the pairs worth intersecting.

    The threshold exists to absorb arithmetic, and nothing else. Two surfaces
    that merely touch bound no volume between them, but a boolean over
    tessellated or imperfectly coincident faces answers with a sliver of a few
    thousandths of a cubic millimetre rather than with zero. The default floor
    is 0.05 mm^3: orders of magnitude below any overlap a person would call
    one, and above the noise.

    It is deliberately not a place to put anything else. An overlap that is
    meant to be there is a property of the joint between those two parts, and is
    read from that joint.

    Every one of them is read from the joint, and none is declared against the
    pair. Two parts have exactly one relationship - the 'connect' that joins
    them - so that is the only place a statement about the two of them can live
    and still be true when one of them moves, is renamed, or is used elsewhere.

    - an interface that declares 'selfScrew' cuts its own thread wherever it is
      used, so the two solids occupy the same space where that thread is formed;
    - a mating that declares 'selfScrew' says it of the pairing, which is the
      only place it can be said when neither end knows on its own: the same
      screw cuts its own thread in a pilot hole and cuts nothing in a clearance
      one;
    - a mating that declares 'snapIn' says the pairing is made by pushing one
      past the other rather than screwing it in - a bore onto a thread it is
      not cut to match, a LEGO stud into an anti-stud. Getting past means
      passing through, and a model that holds no springs holds them
      overlapping;
    - a connection whose 'how' declares either of those says it of this joint
      alone: an ordinary screw driven into soft material cuts a thread there
      too, which is a fact about the joint and not about the screw;
    - a connection's 'interferes' names the further items the same act of
      joining drives through, which nothing about the connection can imply: a
      bolt is connected to one part and passes through the three behind it.

    An overlap between two parts joined in any of those ways is expected, and
    is not reported. Every other overlap between them still is: a screw may
    bite the bracket it is driven into without also being inside the housing.

        assemblies:
          gearbox:
            interference:
              minVolume: 0.01     # a tighter floor, for geometry that is exact
    """

    def __init__(self) -> None:
        super().__init__("interference")

    async def cache_key_suffix(self, ctx, shape) -> str:
        config = (shape.config or {}).get("interference") or {}
        return ",manufacturable=%s,minVolume=%s,minFraction=%s" % (
            bool(getattr(shape, "is_manufacturable", True)),
            config.get("minVolume", DEFAULT_MIN_VOLUME),
            config.get("minFraction", 0.0),
        )

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        config = (shape.config or {}).get("interference") or {}

        # Worked out before the geometry is, so that the pairs the joints
        # account for are never measured. They are still filtered out of the
        # answer below: that is what decides the verdict, and it does not
        # depend on the wrapper having skipped them.
        plan = await _plan(ctx, shape)
        expected = plan.expected

        verdict = self.TEST_PASSED
        for problem in plan.problems:
            verdict = self.failed(shape, problem)

        # Every declared sub-assembly answers for its own inside, with its own
        # verdict - cached against its own hash, so asked of a sub-assembly
        # already checked it costs a lookup. Taken once per object, however
        # many times the object is placed: two sidepods are one sidepod.
        taken = set()
        for path, subassembly in plan.subassemblies:
            if id(subassembly) in taken:
                continue
            taken.add(id(subassembly))
            if not await self.test_cached(tests_to_run, ctx, subassembly, test_ctx):
                verdict = self.failed(shape, "'%s' does not pass on its own" % path)

        try:
            result = await shape.get_interference_async(
                ctx,
                min_volume=float(config.get("minVolume", DEFAULT_MIN_VOLUME)),
                min_fraction=float(config.get("minFraction", 0.0)),
                expected=sorted(expected),
                opaque=sorted(set(plan.opaque)),
            )
        except Exception as e:
            # Not a pass. An assembly that will not realize returns None below
            # and is the 'cad' test's business; reaching here instead means the
            # check itself broke, and reporting that as "no interference found"
            # is how a check comes to certify what it never looked at.
            #
            # It did: json.dumps() cannot encode the BREP bytes the envelope
            # carries, the TypeError landed here, and every assembly passed
            # without being examined. The message was at debug level, so
            # nothing said so.
            test_ctx[self.NOT_CACHEABLE] = True
            return self.failed(shape, "the interference check could not be run: %s" % e)

        if result is None:
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "The assembly produced no geometry to check")
            return verdict

        # Said out loud rather than left to be inferred from a pass. A shape
        # that is not a valid solid cannot be intersected meaningfully - an
        # inside-out one "shares" volume with parts it is nowhere near - so it
        # is left out, and an assembly built entirely from such parts is not
        # being checked at all. Whoever reads a pass should know which it was.
        # A verdict reached while some of it could not be looked at is not a
        # verdict about the assembly, and remembering it would hand back a pass
        # that was never earned - without even repeating what went unexamined,
        # since a cached result is returned before the test runs.
        indeterminate = result.get("indeterminate") or []
        unchecked = result.get("unchecked") or []
        if indeterminate or unchecked:
            test_ctx[self.NOT_CACHEABLE] = True

        if unchecked:
            shown = ", ".join(unchecked[:5]) + ("..." if len(unchecked) > 5 else "")
            self.info(
                shape,
                "%d part(s) are not valid solids and were not checked: %s" % (len(unchecked), shown),
            )

        # A pair whose boolean did not come back is not a pair that does not
        # overlap. Saying so is the difference between a check that found
        # nothing and a check that could not look.
        for pair in indeterminate:
            self.info(
                shape,
                "could not decide whether '%s' and '%s' overlap: %s"
                % (pair["a"], pair["b"], pair.get("reason", "the boolean failed")),
            )

        overlaps = result.get("overlaps") or []
        reported = [o for o in overlaps if not _is_expected(o, expected)]
        if not reported:
            return self.passed(shape) if verdict else verdict

        # An assembly that says it is not manufacturable is a record of
        # something rather than something being built - an import kept as it
        # arrived, a model of what somebody else makes. It is still told what
        # it contains; it is not failed for it. See 'Test.warned'.
        say = self.failed if getattr(shape, "is_manufacturable", True) else self.warned
        for overlap in reported:
            said = say(
                shape,
                "'%s' and '%s' share %.3f mm^3" % (overlap["a"], overlap["b"], overlap["volume"]),
            )
            verdict = verdict and said
        return verdict


class _Plan:
    """What an assembly's joints say about the overlaps inside it, and what it leaves to others.

    'expected' holds pairs of subtrees - a part, or a whole sub-assembly - by
    their path from the assembly being checked, exactly as the interference
    wrapper names the nodes of the tree it is handed. A pair is kept as the
    joint declared it rather than expanded into every pair of parts under the
    two: it is cheaper to carry, and it is what says which joint excused an
    overlap.

    'opaque' holds the declared sub-assemblies under it, by path. Each is an
    object with a verdict of its own - its own 'interference' test, cached
    against its own hash - which the assembly takes rather than repeats, so
    only what crosses the boundary of one is looked at here. 'subassemblies'
    is the same, with the objects, for taking those verdicts.

    'problems' are declarations that cannot be honoured: an 'interferes:'
    naming something that is not a named link where it is written.
    """

    def __init__(self):
        self.expected = set()
        self.opaque = []
        self.subassemblies = []
        self.problems = []


def _children(assembly):
    return list(getattr(assembly, "children", None) or [])


def _is_assembly(item):
    return isinstance(item, Assembly)


def _is_container(item):
    """A 'links:' list written inside an ASSY file: part of the assembly that holds it."""
    return _is_assembly(item) and bool((getattr(item, "config", None) or {}).get("child", False))


def _link_name(node, index, child):
    """What 'node' addresses its child at 'index' by.

    'Assembly.link_name' where there is one, which is the one definition of it
    and is what the geometry is labelled with ('Assembly._child_name_label') -
    so a path built here names the same nodes as the tree the overlaps are
    reported against. A tree handed to this check that is not an 'Assembly'
    answers the same question the same way, by the same rule.
    """
    link_name = getattr(node, "link_name", None)
    if link_name is not None:
        return link_name(index)
    return child.name if child.name is not None else assy_filter.synthetic_link_name(index)


def _join(prefix, label):
    return "%s/%s" % (prefix, label) if prefix else label


def _named_links(assembly, prefix, address="", found=None):
    """{address: path} of every link an 'interferes:' written in 'assembly' can name.

    Addressed exactly as 'map:' addresses nodes (see 'assembly_ports.node_index'):
    by the path of link names that reaches it, 'container/name' for one inside a
    container. Every link has a name (see 'Assembly.link_name'), so every one of
    them can be named -- including a 'links:' container that gave itself none,
    which is 'link#2' and is a level of the path like any other.

    A declared sub-assembly is the one thing addressable as a whole and never
    reached into: to excuse an overlap with something inside one, name the
    sub-assembly. The address and the path differ only by 'prefix', which is
    what the connection is written relative to.
    """
    found = {} if found is None else found
    for index, child in enumerate(_children(assembly)):
        label = _link_name(assembly, index, child)
        path = _join(prefix, label)
        child_address = _join(address, label)
        found.setdefault(child_address, path)
        if _is_container(getattr(child, "item", None)):
            _named_links(child.item, path, child_address, found)
    return found


def _addressed(assembly, address):
    """The child item at 'address' in 'assembly' and its path under it, or None."""
    for found_address, path in _named_links(assembly, "").items():
        if found_address == address:
            item = _item_at(assembly, path)
            return (item, path) if item is not None else None
    return None


def _item_at(assembly, path):
    """The item the child at 'path' (built from labels) holds."""
    node = assembly
    item = None
    remaining = path
    while remaining:
        for index, child in enumerate(_children(node)):
            label = _link_name(node, index, child)
            if remaining == label or remaining.startswith(label + "/"):
                item = getattr(child, "item", None)
                remaining = remaining[len(label) + 1 :]
                node = item
                break
        else:
            return None
    return item


async def _port_owner(item, path, port):
    """The part that provides 'port' of the item at 'path', as a path under the assembly being checked.

    A part provides its own ports. An assembly provides the ones its 'map:'
    externalizes, and each of those names a node of it and a port or interface
    instance of that node - which is followed, level by level, to the part at
    the end of the chain. A mapped instance's ports are named after the map
    entry ('<entry>-<port of the interface>'), so the entry and the inner port
    are both read off the name.

    Where the chain cannot be followed - a port the assembly declares itself
    rather than maps - the assembly as a whole is the answer: correct, if less
    precise.
    """
    if not _is_assembly(item) or not port:
        return path
    best = None
    for key, spec in ((item.config or {}).get("map") or {}).items():
        if not isinstance(spec, (list, tuple)) or not spec:
            continue
        if len(spec) == 2 and port == key:
            best = (key, spec[0], spec[1])
            break
        if len(spec) == 3 and port.startswith(key + "-") and (best is None or len(key) > len(best[0])):
            best = (key, spec[0], spec[2] + port[len(key) :])
    if best is None:
        return path
    instantiate = getattr(item, "do_instantiate", None)
    if instantiate is not None:
        await instantiate()
    found = _addressed(item, best[1])
    if found is None:
        return path
    node_item, node_path = found
    return await _port_owner(node_item, _join(path, node_path), best[2])


async def _joint_overlaps(ctx, child, connection):
    """Whether the joint itself says its two items share space where they meet."""
    how = getattr(child, "how", None)
    if how is not None and (getattr(how, "self_screw", False) or getattr(how, "snap_in", False)):
        return True
    for key in ("with_interface", "to_interface"):
        if await _cuts_its_own_thread(ctx, connection.get(key)):
            return True
    return False


async def _plan(ctx, shape):
    """What 'shape''s joints expect to overlap, and which sub-assemblies answer for themselves.

    Read at every level the assembly's own ASSY file writes - the file's links
    and every 'links:' list nested in it, named or not - because that is where
    the joints are, and each is resolved where it is written: its two ends are
    siblings there. A declared sub-assembly is not descended into; it is where
    its own joints are read, by its own check.

    Four ways a joint says its items overlap, none a property of the assembly:
    an interface that cuts its own thread wherever it is used, a connection
    that says this joint cuts one or snaps past a feature ('how'), and a
    connection that names the further links the same act of joining drives
    through ('interferes:'). The first three are about the two ends, and are
    resolved through any 'map:' to the parts that provide the joined ports.
    The last names links - parts or assemblies, by name - and is kept as the
    pair of subtrees it names.
    """
    plan = _Plan()
    instantiate = getattr(shape, "do_instantiate", None)
    if instantiate is not None:
        # The children, and the connections on them, exist only once the
        # assembly has been instantiated.
        await instantiate()
    await _plan_level(ctx, shape, "", plan, shape)
    return plan


async def _plan_level(ctx, level, prefix, plan, root):
    children = _children(level)
    paths = {}
    for index, child in enumerate(children):
        path = _join(prefix, _link_name(level, index, child))
        paths[id(child)] = path
        item = getattr(child, "item", None)
        if _is_container(item):
            await _plan_level(ctx, item, path, plan, root)
        elif _is_assembly(item):
            plan.opaque.append(path)
            plan.subassemblies.append((path, item))

    siblings = {_link_name(level, index, child): child for index, child in enumerate(children)}
    named = None
    for child in children:
        connection = getattr(child, "connection", None)
        if not connection:
            continue
        here = paths[id(child)]
        target = siblings.get(connection.get("target"))
        if target is not None and await _joint_overlaps(ctx, child, connection):
            plan.expected.add(
                (
                    await _port_owner(getattr(child, "item", None), here, connection.get("with_port")),
                    await _port_owner(getattr(target, "item", None), paths[id(target)], connection.get("to_port")),
                )
            )
        for name in connection.get("interferes") or []:
            if named is None:
                named = _named_links(level, prefix)
            other = named.get(name)
            if other is None:
                plan.problems.append(
                    "'%s' names '%s' in 'interferes:', which is not a link%s"
                    % (here, name, " of '%s'" % prefix if prefix else "")
                )
                continue
            plan.expected.add((here, other))


async def _cuts_its_own_thread(ctx, interface_spec):
    if not interface_spec:
        return False
    try:
        interface = ctx.get_interface(interface_spec)
    except Exception:
        return False
    if interface is None:
        return False
    try:
        return bool(interface.get_self_screw())
    except Exception:
        return False


def _is_expected(overlap, expected):
    """Whether this overlap lies between two subtrees a joint says share space."""
    a, b = overlap["a"], overlap["b"]
    for x, y in expected:
        if (_within(a, x) and _within(b, y)) or (_within(a, y) and _within(b, x)):
            return True
    return False


def _within(path, root):
    """Whether 'path' is 'root' or anything under it - the one rule pairs are named by.

    Repeated in the interference wrapper, which runs where PartCAD cannot be
    imported; a test holds the two to each other. Paths are exact, from the
    assembly being checked down, so 'battery' covers 'battery/pin-1' and never
    'spare-battery' or 'tub/battery'.
    """
    return path == root or path.startswith(root + "/")
