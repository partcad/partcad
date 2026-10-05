#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Build vs Buy, and the order things are built in once that is decided.

Every line item of an object can be bought, or built - a part made from its
stock, an assembly put together from its links - and some can be either. Which
of the two the user picked decides what else there is to do: a part that is
bought needs nothing from its stock, an assembly that is bought needs nothing of
what is inside it. Two things are answered here from that one decision, so that
everything that asks either question gets the same answer:

* **The tree** (`tree_async`): the object as its line items - every link of an
  assembly, every sub-assembly's links in turn, the stock a part is made from
  and that stock's stock - with what each one *can* be: bought (it declares a
  vendor and an SKU), built (it carries manufacturing instructions, or links to
  put together), both, or neither. No geometry is built for it, so it is as
  cheap as a bill of materials. The IDE's Build vs Buy table is drawn from it,
  and the IDE works out the rows and their counts itself, as the user toggles.

* **The plan** (`plan`): what has to be done, in the order it has to be done
  in, given the user's choices. It is what the IDE's Build tab lists on the
  left, and the order the pages of the assembly instructions are written in
  (`assembly_guide`), so that the item selected in one and the page of the other
  are the same step by construction rather than by two implementations agreeing.

The choice of one item is `effective_choice`: forced where only one of the two
is possible, the user's where both are, and "buy" where both are and the user
has not said - which is also what the bill of materials and the cart assume (see
'partcad.procurement').

The plan of an assembly is the tree of its links, in the order the ASSY file
lists them, with an item prepended to a link for each thing that has to be made
before that link can be added: the part it adds, when that part is built (and
before it, the stock it is made from, when that is built too), or the
sub-assembly it adds, when that is built - only in the recursive plan, since
otherwise a sub-assembly is something handed over ready. A thing used in several
places is made once, by the item that says how many: it is placed in the
lowest-level assembly that holds every place it is used in, just before the
first link of that assembly that needs it. An assembly nested in its parent's
own file (an embedded one) is always put together first, wherever it is, since
nobody can hand it over.

The plan of a part is a list: the part last, and before it the stock it is made
from - and that stock's stock - as far back as the first one that is bought.

The names of the user's choices and the escaping of the file they are saved in
are 'partcad_utils.garage'; the IDE implements the effective choice and the
counting of rows a second time, in TypeScript ('ide/vscode/src/webview/bvb.ts'),
because it recounts on every toggle without a round trip. The rule is written
in both places in the same words; change it in both.
"""

from dataclasses import dataclass, field
from typing import Optional

from partcad_utils.garage import BUILD, BUY, CHOICES

from . import procurement
from .assembly import Assembly

# How deep a chain of stock is followed: the cycle guard 'procurement' uses.
MAX_STOCK_DEPTH = procurement.MAX_STOCK_DEPTH

ITEM_PART = "part"
ITEM_ASSEMBLY = "assembly"
ITEM_LINK = "link"
ITEM_MANUFACTURE = "manufacture"

ROOT_ID = "root"


#
# The tree
#


@dataclass
class TreeIndex:
    """The objects behind the nodes of a tree, by node id.

    Kept beside the tree rather than in it, because the tree is plain data that
    crosses the wire and an object does not.
    """

    objects: dict = field(default_factory=dict)


def _qualified(obj) -> str:
    return "%s:%s" % (obj.project_name, obj.name)


def _material(obj) -> Optional[str]:
    reference = getattr(obj, "material_reference", None)
    return reference() if reference is not None else None


def _step_source(assembly):
    # Imported here: 'assembly_guide' imports this module.
    from .assembly_guide import _step_source

    return _step_source(assembly)


def _resolve_alias(ctx, assembly):
    from .assembly_guide import resolve_alias

    return resolve_alias(ctx, assembly)


async def tree_async(ctx, obj, force_manufacturing: bool = False) -> tuple:
    """The tree of an object's line items, and the objects behind it.

    Returns '(tree, index)'. See the module docstring for what the tree is, and
    the contract its fields keep in 'ide/vscode/src/webview/messages.ts'.

    Each node says what 'pc test -f manufacturability' would let it be, as far
    as that can be known from the declarations alone (see
    '_manufacturable', '_part_problems' and '_assembly_problems'). Whether a
    supplier has it today, whether its geometry suits its method and whether its
    software can be fetched are not here: they are the market's question and the
    geometry's, which 'pc test' and the Buy tab ask.

    'force_manufacturing' is '--ignore-manufacturability': the object is to be
    taken as manufacturable whatever it says, and so is everything in it.
    """
    index = TreeIndex()
    tree = await _node_async(ctx, obj, "0", None, None, index, 0, force_manufacturing)
    return tree, index


def _manufacturable(obj, forced: bool) -> bool:
    """Whether an object is meant to be made at all, where it is used.

    'manufacturable: false' on an object, or on its package (which every object
    of the package inherits, and every package imported below it), says that it
    is not designed to be made: a vendor's reference model, a placeholder, an
    example. It is a statement about the object *on its own*: an object used
    inside an assembly that is manufacturable has to be had whatever it says
    about itself, which is the 'force_manufacturing' the manufacturability test
    hands everything below a manufacturable assembly and the stock of a
    manufacturable part. So does this, by passing 'forced' down.
    """
    return forced or bool(getattr(obj, "is_manufacturable", True))


def _part_problems(part, made: bool, bought: bool) -> list:
    """What stops a part from being made, of what 'pc test' checks without geometry.

    Only asked of a part that says how it is made. Each is a failure of the
    manufacturability test's part path, worded as the test words it.
    """
    from .file_factory import unreproducible_reason
    from .part_config import PartConfiguration
    from .shape_config import final_config

    problems = []
    if not made:
        return problems
    data = PartConfiguration.get_manufacturing_data(part)
    if data.machine_error:
        problems.append("The machine it is made on cannot be read: %s" % data.machine_error)
    missing = data.missing_fields()
    if missing:
        problems.append("Its manufacturing instructions do not say: %s" % ", ".join(missing))
    if not bought:
        # A bought part is identified by what it is ordered as; one that is made
        # is identified by the file it is made from, which has to be pinned.
        failure = unreproducible_reason(final_config(part))
        if failure:
            problems.append("It is not reproducible: %s" % failure)
    return problems


async def _tolerance_problem(part) -> Optional[str]:
    from .test.manufacturability import tolerance_failure

    try:
        return await tolerance_failure(part)
    except Exception as e:  # pylint: disable=broad-except
        return "Its manufacturing tolerance cannot be read: %s" % e


def _assembly_problems(assembly, content, bought: bool) -> list:
    """What stops an assembly from being put together, of what 'pc test' checks without geometry.

    An assembly is put together by following its Assembly YAML (ASSY) file - the
    one manufacturing method an assembly has (see
    'assembly_config_manufacturing') - so one imported whole from a STEP or URDF
    file has links to show but no steps to put them together by, and the
    manufacturability test says "Can't be assembled" of it. One that is an ASSY
    file has to say, for every step, what it joins and how ('Assembly.
    get_step_problems', which the caller adds once the steps are read).
    """
    from .assembly_config import AssemblyConfiguration
    from .file_factory import unreproducible_reason
    from .shape_config import final_config

    problems = []
    if not content.children:
        return problems
    if AssemblyConfiguration.get_manufacturing_data(assembly).method is None:
        problems.append(
            "It is a '%s' assembly, not an Assembly YAML (ASSY) file, so there are no steps to put it together by"
            % (assembly.config.get("type") or "unknown")
        )
    if not bought:
        failure = unreproducible_reason(final_config(assembly))
        if failure:
            problems.append("It is not reproducible: %s" % failure)
    return problems


async def _node_async(ctx, obj, node_id, link, parent_name, index, depth, forced=False) -> dict:
    index.objects[node_id] = obj
    if isinstance(obj, Assembly):
        return await _assembly_node_async(ctx, obj, node_id, link, parent_name, index, depth, forced)
    return await _part_node_async(ctx, obj, node_id, link, index, depth, forced)


async def _assembly_node_async(ctx, assembly, node_id, link, parent_name, index, depth, forced=False) -> dict:
    embedded = bool(assembly.config.get("child", False))
    target = _resolve_alias(ctx, assembly)
    await target.do_instantiate()
    content = _step_source(target)
    # An embedded assembly belongs to no package, so it has no name to be looked
    # up or ordered by; it is named after where it is.
    name = "%s/%s" % (parent_name, link) if embedded and parent_name else _qualified(assembly)
    store = assembly.get_store_data()
    bought = (not embedded) and assembly.is_declared_purchasable()
    # An embedded assembly is part of its parent's file, and is put together by
    # it: its steps are the parent's to answer for.
    problems = [] if embedded else _assembly_problems(target, content, bought)
    if not embedded and content.children and not problems:
        # Its steps, the ones of the assemblies nested in its file included,
        # each have to say what they join and how (see 'get_step_problems').
        problems.extend("%s: %s" % (step, problem) for step, problem in await target.get_step_problems())
    # An embedded assembly has no declaration of its own to say it in: it is
    # whatever the assembly it is written in is.
    manufacturable = forced if embedded else _manufacturable(assembly, forced)
    node = {
        "id": node_id,
        "name": name,
        "kind": ITEM_ASSEMBLY,
        "link": link,
        "desc": getattr(assembly, "desc", None),
        "buy": bought,
        "build": bool(content.children) and not problems,
        "manufacturable": manufacturable,
        "problems": problems,
        "vendor": store.vendor,
        "sku": store.sku,
        "material": _material(assembly),
    }
    if embedded:
        node["embedded"] = True
    children = []
    for position, child in enumerate(content.children):
        child_link = child.name or child.item.name
        children.append(
            await _node_async(
                ctx,
                child.item,
                "%s/%d" % (node_id, position),
                child_link,
                name,
                index,
                depth + 1,
                manufacturable,
            )
        )
    node["children"] = children
    return node


async def _part_node_async(ctx, part, node_id, link, index, depth, forced=False) -> dict:
    index.objects[node_id] = part
    store = part.get_store_data()
    bought = procurement.is_bought(part)
    made = procurement.is_made(part)
    problems = _part_problems(part, made, bought)
    if made:
        tolerance = await _tolerance_problem(part)
        if tolerance:
            problems.append(tolerance)
    manufacturable = _manufacturable(part, forced)
    node = {
        "id": node_id,
        "name": _qualified(part),
        "kind": ITEM_PART,
        "link": link,
        "desc": getattr(part, "desc", None),
        "buy": bought,
        "build": made and not problems,
        "manufacturable": manufacturable,
        "problems": problems,
        "vendor": store.vendor,
        "sku": store.sku,
        "material": _material(part),
    }
    # Followed whenever it says how it is made, problems or not: the stock is a
    # line of its own, with problems of its own to show.
    stock = procurement.stock_name(part) if made else None
    if stock is not None and depth < MAX_STOCK_DEPTH:
        stock_id = node_id + "/s"
        resolved = await procurement.get_part_async(ctx, stock)
        if resolved is None:
            # Kept as the name it was written as, the way the bill of materials
            # keeps it, so that the table says what is missing.
            node["stock"] = {
                "id": stock_id,
                "name": stock,
                "kind": ITEM_PART,
                "link": None,
                "desc": None,
                "buy": False,
                "build": False,
                "manufacturable": manufacturable,
                "problems": ["%s is not found" % stock],
                "vendor": None,
                "sku": None,
                "material": None,
                "missing": True,
            }
        else:
            # The stock of a manufacturable part has to be had, whatever it
            # says about itself: the test's 'stock_failure' forces it too.
            node["stock"] = await _part_node_async(ctx, resolved, stock_id, None, index, depth + 1, manufacturable)
    return node


def is_missing(node: dict) -> bool:
    """Whether a line item can be had at all: neither bought nor built.

    Missing is one of three things: it declares no vendor and SKU and cannot be
    built (no instructions, or instructions that do not hold up - see
    'problems'); it is a stock reference that resolves to nothing; or it is not
    meant to be made, 'manufacturable: false', where nothing manufacturable it
    is used in overrides that. An embedded assembly is never missing: it is
    part of its parent's file.
    """
    if node.get("embedded"):
        return False
    if node.get("missing") or node.get("manufacturable") is False:
        return True
    return not node.get("buy") and not node.get("build")


def effective_choice(node: dict, choices: Optional[dict] = None) -> str:
    """Whether one line item is built or bought.

    Forced where only one of the two is possible, and the user's choice where
    both are, "buy" until they make one. Something missing (see 'is_missing')
    is neither, and reads as bought: nothing is built out of it, so nothing
    under it is needed.
    """
    if node.get("embedded"):
        return BUILD
    if is_missing(node):
        return BUY
    buy, build = bool(node.get("buy")), bool(node.get("build"))
    if buy and build:
        chosen = (choices or {}).get(node["name"])
        return chosen if chosen in CHOICES else BUY
    return BUILD if build else BUY


#
# The plan
#


@dataclass
class PlanItem:
    id: str
    type: str
    name: str
    title: str
    count: int = 1
    kind: Optional[str] = None
    link: Optional[str] = None
    step: Optional[int] = None
    children: list = field(default_factory=list)
    # What the item is about, for whoever writes its page: the tree node (the
    # first place it occurs) and, for a link, the key of the assembly it is a
    # link of. Neither crosses the wire.
    node: Optional[dict] = None
    container: Optional[str] = None

    def to_data(self) -> dict:
        data = {"id": self.id, "type": self.type, "name": self.name, "title": self.title, "count": self.count}
        if self.kind is not None:
            data["kind"] = self.kind
        if self.link is not None:
            data["link"] = self.link
        if self.step is not None:
            data["step"] = self.step
        if self.type in (ITEM_PART, ITEM_ASSEMBLY):
            data["children"] = [child.to_data() for child in self.children]
        return data

    def walk(self):
        """This item and every item under it, in the order they are read."""
        yield self
        for child in self.children:
            yield from child.walk()


def _counted(title: str, count: int) -> str:
    return "%s (%d)" % (title, count) if count > 1 else title


def plan(tree: dict, choices: Optional[dict] = None, recursive: bool = False, build_parts: bool = True) -> PlanItem:
    """What has to be done to have the object of 'tree', in order.

    'recursive' puts the sub-assemblies that are built into the plan, each as
    an item holding its own plan; otherwise a sub-assembly is a link like any
    other. 'build_parts' puts in the parts that are built, each as an item of
    its own; without it the plan of an assembly is its links alone.
    """
    if tree.get("kind") == ITEM_PART:
        return _part_plan(tree, choices)
    return _AssemblyPlanner(tree, choices or {}, recursive, build_parts).run()


def _part_plan(tree: dict, choices) -> PlanItem:
    """The stock chain of a part that is built, deepest first and the part last."""
    chain = []
    node = tree
    while node is not None and not node.get("missing") and effective_choice(node, choices) == BUILD:
        chain.append(node)
        node = node.get("stock")
    root = PlanItem(id=ROOT_ID, type=ITEM_PART, name=tree["name"], title=tree["name"], kind=ITEM_PART, node=tree)
    for made in reversed(chain):
        root.children.append(_manufacture_item(made, 1))
    return root


def _manufacture_item(node: dict, count: int) -> PlanItem:
    return PlanItem(
        id="make:%s" % node["name"],
        type=ITEM_MANUFACTURE,
        name=node["name"],
        title=_counted("Manufacture %s" % node["name"], count),
        count=count,
        kind=ITEM_PART,
        node=node,
    )


@dataclass
class _Def:
    """One thing that is made once: an assembly put together, or a part made."""

    key: str
    node: dict
    container: bool
    count: int = 0
    # The assemblies (by key) that it is used in directly.
    used_in: set = field(default_factory=set)
    # The things (by key) made out of it, for stock.
    made_into: set = field(default_factory=set)
    # Where it ends up: the key of the assembly whose plan it is an item of.
    placement: Optional[str] = None


class _AssemblyPlanner:
    def __init__(self, tree, choices, recursive, build_parts):
        self.tree = tree
        self.choices = choices
        self.recursive = recursive
        self.build_parts = build_parts
        self.defs = {}
        self.order = []
        self.emitted = set()

    # What is made, and how many

    def _expanded(self, node) -> bool:
        """Whether an assembly's links are part of this plan."""
        if node.get("embedded"):
            return True
        return self.recursive and effective_choice(node, self.choices) == BUILD

    def _made(self, node) -> bool:
        """Whether a part is made, in this plan."""
        return self.build_parts and not node.get("missing") and effective_choice(node, self.choices) == BUILD

    def _def(self, key, node, container) -> _Def:
        found = self.defs.get(key)
        if found is None:
            found = self.defs[key] = _Def(key=key, node=node, container=container)
            self.order.append(key)
        return found

    def _container_key(self, node, parent_key, position) -> str:
        # An embedded assembly is a fresh object wherever it is, so it is keyed by
        # where it is - in the definition of its parent, so that a sub-assembly
        # used twice has its nested assembly made the same way both times.
        if node.get("embedded"):
            return "%s/%d" % (parent_key, position)
        return node["name"]

    def _count(self, node, key, multiplicity):
        """Walk the links under an assembly, counting what is made."""
        for position, child in enumerate(node.get("children") or []):
            if child["kind"] == ITEM_ASSEMBLY:
                if not self._expanded(child):
                    continue
                child_key = self._container_key(child, key, position)
                made = self._def(child_key, child, container=True)
                made.count += multiplicity
                made.used_in.add(key)
                self._count(child, child_key, multiplicity)
            elif self._made(child):
                made = self._def(child["name"], child, container=False)
                made.count += multiplicity
                made.used_in.add(key)
                self._count_stock(child, multiplicity)

    def _count_stock(self, node, multiplicity):
        """One piece of each built stock per part made from it, all the way down."""
        stock = node.get("stock")
        depth = 0
        while stock is not None and self._made(stock) and depth < MAX_STOCK_DEPTH:
            made = self._def(stock["name"], stock, container=False)
            made.count += multiplicity
            made.made_into.add(node["name"])
            node, stock = stock, stock.get("stock")
            depth += 1

    # Where it is made

    def _parent(self, key):
        return None if key == ROOT_ID else self.defs[key].placement

    def _depth(self, key) -> int:
        depth = 0
        while key != ROOT_ID:
            key = self._parent(key)
            depth += 1
        return depth

    def _lowest_common(self, keys) -> str:
        """The lowest-level assembly of the plan that holds every one of 'keys'."""
        keys = list(keys)
        common = keys[0]
        for other in keys[1:]:
            a, b = common, other
            da, db = self._depth(a), self._depth(b)
            while da > db:
                a, da = self._parent(a), da - 1
            while db > da:
                b, db = self._parent(b), db - 1
            while a != b:
                a, b = self._parent(a), self._parent(b)
            common = a
        return common

    def _place(self):
        """Decide which assembly's plan each thing is made in.

        An assembly before what it holds, and a part before its stock, since
        where a thing is needed is where the things that need it are made. The
        definitions are an acyclic graph - an assembly cannot hold itself, and
        a chain of stock is cut off at 'MAX_STOCK_DEPTH' - so this terminates.
        """
        pending = list(self.order)
        while pending:
            progressed = False
            for key in list(pending):
                made = self.defs[key]
                needs = set(made.used_in)
                waiting = False
                for user in made.made_into:
                    placement = self.defs[user].placement if user in self.defs else None
                    if placement is None:
                        waiting = True
                        break
                    needs.add(placement)
                if waiting or any(user != ROOT_ID and self.defs[user].placement is None for user in made.used_in):
                    continue
                if made.node.get("embedded"):
                    # Made right where it is used: there is only one place.
                    made.placement = next(iter(made.used_in))
                else:
                    made.placement = self._lowest_common(needs) if needs else ROOT_ID
                pending.remove(key)
                progressed = True
            if not progressed:
                # Nothing left that can be placed: a cycle the walk did not
                # cut. Whatever remains is made at the top, which is never wrong,
                # only less specific.
                for key in pending:
                    self.defs[key].placement = ROOT_ID
                break

    # The items, in order

    def _postorder(self, node, key, position, out):
        """What has to be made for one link, deepest first."""
        if node["kind"] == ITEM_ASSEMBLY:
            if not self._expanded(node):
                return
            child_key = self._container_key(node, key, position)
            for child_position, child in enumerate(node.get("children") or []):
                self._postorder(child, child_key, child_position, out)
            out.append(child_key)
            return
        if not self._made(node):
            return
        chain = []
        stock = node.get("stock")
        while stock is not None and self._made(stock) and len(chain) < MAX_STOCK_DEPTH:
            chain.append(stock["name"])
            stock = stock.get("stock")
        out.extend(reversed(chain))
        out.append(node["name"])

    def _items(self, node, key) -> list:
        """The items of one assembly's plan."""
        items = []
        for position, child in enumerate(node.get("children") or []):
            needed = []
            self._postorder(child, key, position, needed)
            for made_key in needed:
                made = self.defs.get(made_key)
                if made is None or made.placement != key or made_key in self.emitted:
                    continue
                self.emitted.add(made_key)
                items.append(self._made_item(made))
            items.append(
                PlanItem(
                    id="%s#%d" % (key, position),
                    type=ITEM_LINK,
                    name=child["name"],
                    title=child.get("link") or child["name"],
                    kind=child["kind"],
                    link=child.get("link"),
                    step=position,
                    node=child,
                    container=key,
                )
            )
        return items

    def _made_item(self, made: _Def) -> PlanItem:
        if not made.container:
            return _manufacture_item(made.node, made.count)
        title = made.node.get("link") if made.node.get("embedded") else made.node["name"]
        item = PlanItem(
            id=made.key,
            type=ITEM_ASSEMBLY,
            name=made.node["name"],
            title=_counted(title or made.node["name"], made.count),
            count=made.count,
            kind=ITEM_ASSEMBLY,
            node=made.node,
            container=made.key,
        )
        item.children = self._items(made.node, made.key)
        return item

    def run(self) -> PlanItem:
        root = PlanItem(
            id=ROOT_ID,
            type=ITEM_ASSEMBLY,
            name=self.tree["name"],
            title=self.tree["name"],
            kind=ITEM_ASSEMBLY,
            node=self.tree,
            container=ROOT_ID,
        )
        if effective_choice(self.tree, self.choices) != BUILD:
            # Bought whole: there is nothing to do but to order it.
            return root
        self._count(self.tree, ROOT_ID, 1)
        self._place()
        root.children = self._items(self.tree, ROOT_ID)
        return root


def has_build(tree: dict, choices: Optional[dict] = None) -> bool:
    """Whether anything that is needed at all is built: what the Build tab is for."""

    def visit(node) -> bool:
        if node.get("missing"):
            return False
        choice = effective_choice(node, choices)
        if choice == BUILD and not node.get("embedded"):
            return True
        if choice != BUILD:
            return False
        if node.get("stock") is not None and visit(node["stock"]):
            return True
        return any(visit(child) for child in node.get("children") or [])

    return visit(tree)
