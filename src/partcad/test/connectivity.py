#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

from .test import Test
from ..assembly import Assembly


class ConnectivityTest(Test):
    """Fail an assembly whose parts are placed in ways that do not add up.

    Three things, all of which an assembly can do while building perfectly and
    rendering plausibly.

    **The same part twice in the same place.** A generator that runs a loop one
    time too many, or a hand-written ASSY with a copy-pasted node whose location
    was not changed, produces two items occupying one space. Nothing looks
    wrong: the second is exactly behind the first in every view.

    **Two items connected to one port.** A stud takes one brick and a bolt hole
    takes one bolt. Where the joint is one that is genuinely made more than once
    - a shaft carrying several parts along its length, a rail - the interface
    says so with 'multiConnect: true' and this passes it.

    **An item anchored to nothing.** Every item after the first has to be put
    somewhere relative to what is already there. One placed by 'location:' in an
    assembly that otherwise connects by interface is floating in the coordinate
    system rather than attached to the thing it belongs to: it will be in the
    right place only for as long as nothing it sits on moves. This is reported
    rather than assumed wrong - an assembly may legitimately place everything by
    coordinates - so it only applies once something in the assembly does connect.

    Configured per assembly:

        assemblies:
          gearbox:
            connectivity:
              allowDuplicates: false   # two items in one place
              requireAnchored: true    # every item after the first connected
              skip: false
    """

    def __init__(self) -> None:
        super().__init__("connectivity")

    def cache_key_suffix(self, ctx, shape) -> str:
        # Every setting that decides the verdict. Without them a cached pass is
        # read back after the setting that produced it has been turned off.
        config = (shape.config or {}).get("connectivity") or {}
        return ",skip=%s,allowDuplicates=%s,requireAnchored=%s" % (
            bool(config.get("skip", False)),
            bool(config.get("allowDuplicates", False)),
            bool(config.get("requireAnchored", True)),
        )

    async def test(self, tests_to_run: list[Test], ctx, shape, test_ctx: dict = {}) -> bool:
        if not isinstance(shape, Assembly):
            self.debug(shape, "Not applicable")
            return self.TEST_PASSED

        config = (shape.config or {}).get("connectivity") or {}
        if config.get("skip", False):
            self.debug(shape, "Skipped by configuration")
            return self.TEST_PASSED

        try:
            await shape.do_instantiate()
        except Exception as e:
            # An assembly that will not instantiate is the 'cad' test's
            # business, and this verdict turned on that rather than on the
            # assembly: do not remember it.
            test_ctx[self.NOT_CACHEABLE] = True
            self.debug(shape, "Failed to instantiate: %s" % e)
            return self.TEST_PASSED

        children = list(shape.connected_children())
        problems = []
        problems.extend(self._duplicates(children, config))
        problems.extend(await self._crowded_ports(ctx, children))
        problems.extend(self._unanchored(shape, config))

        if not problems:
            return self.passed(shape)
        for problem in problems:
            self.failed(shape, problem)
        return self.TEST_FAILED

    def _duplicates(self, children, config):
        if config.get("allowDuplicates", False):
            return []
        seen = {}
        for child in children:
            item = getattr(child.item, "name", None)
            project = getattr(child.item, "project_name", None)
            location = child.location
            if item is None or location is None:
                continue
            key = (project, item, _packed(location))
            if key in seen:
                yield "'%s' and '%s' are the same part in the same place" % (seen[key], child.name)
                continue
            seen[key] = child.name

    async def _crowded_ports(self, ctx, children):
        """Two items connected to one port, unless the interface allows it.

        Returns a list rather than yielding: asking an interface whether it
        takes more than one item is awaited, and an async generator cannot be
        collected as simply as the other two checks are.
        """
        problems = []
        taken = {}
        for child in children:
            connection = child.connection
            if not connection:
                continue
            target = connection.get("target")
            port = connection.get("to_port")
            interface = connection.get("to_interface")
            if target is None or (port is None and interface is None):
                continue
            key = (target, port, interface)
            if key not in taken:
                taken[key] = child.name
                continue
            if await _allows_many(ctx, interface):
                continue
            where = port if port is not None else interface
            problems.append(
                "'%s' and '%s' are both connected to '%s' of '%s'"
                % (taken[key], child.name, where, target)
            )
        return problems

    def _containers(self, assembly):
        """Each group of items that were written as one 'links:' list.

        An ASSY file's top level 'links:' becomes a child assembly of the object
        the file defines, and so does every nested one, so the groups are the
        assembly's own children and then those of every assembly among them.
        """
        children = list(getattr(assembly, "children", []) or [])
        yield children
        for child in children:
            item = child.item
            if isinstance(item, Assembly):
                yield from self._containers(item)

    def _unanchored(self, shape, config):
        """Items placed by coordinates in a group that otherwise connects.

        Per group rather than per assembly, because the exemption is for the
        item the others hang from and every 'links:' list has one. Flattening
        the tree first would exempt the wrapper assembly that the file's top
        level becomes, and then report the item it wraps - which is the one
        thing that is allowed to be placed by coordinates.

        Only meaningful once something in the group does connect: a group
        written entirely as coordinates is a legitimate way to write one.
        """
        if not config.get("requireAnchored", True):
            return
        for children in self._containers(shape):
            if len(children) < 2:
                continue
            if not any(child.connection for child in children):
                continue
            for child in children[1:]:
                if not child.connection:
                    yield (
                        "'%s' is placed by coordinates among items that connect, "
                        "so nothing holds it where it is" % child.name
                    )


def _packed(location):
    """A location as a hashable key, rounded so that arithmetic noise in two
    placements that were meant to be the same does not hide that they are."""
    try:
        translation, axis, angle = location.as_packed()
        return (
            tuple(round(float(v), 6) for v in translation),
            tuple(round(float(v), 6) for v in axis),
            round(float(angle), 6),
        )
    except Exception:
        return repr(location)


async def _allows_many(ctx, interface_spec):
    """Whether this interface says one instance of it may take several items."""
    if ctx is None or not interface_spec:
        return False
    try:
        interface = ctx.get_interface(interface_spec)
    except Exception:
        return False
    if interface is None:
        return False
    try:
        return bool(interface.get_multi_connect())
    except Exception:
        return False
