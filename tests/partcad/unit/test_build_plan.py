#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What is built, what is bought, and the order the building is done in.

The plan is what the IDE's Build tab lists and the order the assembly
instructions are written in, so these are written against the trees
'build_plan.tree_async' produces, built by hand: the rules are about the tree,
not about how it was read.
"""

from partcad import build_plan
from partcad_utils.garage import BUILD, BUY


def node(name, kind="part", buy=False, build=False, children=None, stock=None, embedded=False, link=None):
    data = {"id": name, "name": name, "kind": kind, "link": link, "buy": buy, "build": build}
    if children is not None:
        data["children"] = children
        data["build"] = bool(children)
    if stock is not None:
        data["stock"] = stock
    if embedded:
        data["embedded"] = True
    return data


def assembly(name, *children, buy=False, embedded=False, link=None):
    return node(name, "assembly", buy=buy, children=list(children), embedded=embedded, link=link)


def bought(name, link=None):
    return node(name, buy=True, link=link)


def made(name, stock=None, buy=False, link=None):
    return node(name, buy=buy, build=True, stock=stock, link=link)


def titles(item):
    """The plan as the left pane shows it: titles, nested as the tree is."""
    if item.children:
        return [item.title, [titles(child) for child in item.children]]
    return item.title


def flat(item):
    return [child.title for child in item.children]


#
# The choice of one item
#


def test_an_item_that_can_only_be_one_thing_is_that_thing_whatever_was_chosen():
    assert build_plan.effective_choice(bought("//p:screw"), {"//p:screw": BUILD}) == BUY
    assert build_plan.effective_choice(made("//p:panel"), {"//p:panel": BUY}) == BUILD


def test_an_item_that_says_neither_is_bought_as_it_is():
    assert build_plan.effective_choice(node("//p:thing")) == BUY


def test_an_item_that_can_be_either_is_bought_until_it_is_chosen_to_be_built():
    both = made("//p:panel", buy=True)
    assert build_plan.effective_choice(both) == BUY
    assert build_plan.effective_choice(both, {"//p:panel": BUILD}) == BUILD
    assert build_plan.effective_choice(both, {"//p:panel": "nonsense"}) == BUY


def test_an_embedded_assembly_is_always_built():
    assert build_plan.effective_choice(assembly("//p:top/head", bought("//p:half"), embedded=True)) == BUILD


#
# A part
#


def test_a_bought_part_has_nothing_to_build():
    plan = build_plan.plan(bought("//p:screw"))
    assert plan.type == build_plan.ITEM_PART
    assert plan.children == []


def test_a_part_is_built_last_after_the_stock_it_is_made_from_that_is_built_too():
    roll = bought("//p:roll")
    sheet = made("//p:sheet", stock=roll, buy=True)
    blank = made("//p:blank", stock=sheet)

    # The sheet can be bought, and is until somebody says otherwise.
    assert flat(build_plan.plan(blank)) == ["Manufacture //p:blank"]
    # Chosen to be built: it is made first, from the roll, which is bought.
    assert flat(build_plan.plan(blank, {"//p:sheet": BUILD})) == ["Manufacture //p:sheet", "Manufacture //p:blank"]


def test_a_missing_stock_stops_the_chain():
    blank = made("//p:blank", stock={**node("//p:gone"), "missing": True})
    assert flat(build_plan.plan(blank)) == ["Manufacture //p:blank"]


#
# An assembly
#


def test_an_assembly_is_its_links_in_order():
    top = assembly("//p:top", bought("//p:base", link="base"), bought("//p:lid", link="lid"))
    plan = build_plan.plan(top)

    assert plan.type == build_plan.ITEM_ASSEMBLY
    assert [(child.type, child.title, child.step) for child in plan.children] == [
        ("link", "base", 0),
        ("link", "lid", 1),
    ]


def test_a_bought_assembly_has_nothing_to_build():
    top = assembly("//p:top", bought("//p:base", link="base"), buy=True)
    assert build_plan.plan(top).children == []
    assert build_plan.plan(top, {"//p:top": BUILD}).children


def test_a_built_part_is_made_once_before_the_first_link_that_needs_it():
    panel = made("//p:panel")
    top = assembly(
        "//p:top",
        bought("//p:frame", link="frame"),
        {**panel, "link": "left"},
        bought("//p:screw", link="screw"),
        {**panel, "link": "right"},
    )

    assert flat(build_plan.plan(top)) == ["frame", "Manufacture //p:panel (2)", "left", "screw", "right"]


def test_without_build_parts_there_are_only_links():
    top = assembly("//p:top", made("//p:panel", link="left"), made("//p:panel", link="right"))
    assert flat(build_plan.plan(top, build_parts=False)) == ["left", "right"]


def test_the_stock_of_a_built_part_is_made_just_before_it():
    sheet = made("//p:sheet", stock=bought("//p:roll"), buy=True)
    top = assembly("//p:top", bought("//p:frame", link="frame"), made("//p:panel", stock=sheet, link="panel"))

    plan = build_plan.plan(top, {"//p:sheet": BUILD})

    assert flat(plan) == ["frame", "Manufacture //p:sheet", "Manufacture //p:panel", "panel"]


def _castle(tower_link="tower"):
    """A castle of two towers and a gate; a tower is a base, a built window and a roof."""
    window = made("//p:window")
    tower = assembly(
        "//p:tower",
        bought("//p:stone", link="stone"),
        {**window, "link": "window"},
        bought("//p:roof", link="roof"),
        link=tower_link,
    )
    return assembly(
        "//p:castle",
        bought("//p:ground", link="ground"),
        {**tower, "link": "east"},
        {**tower, "link": "west"},
        bought("//p:gate", link="gate"),
    )


def test_without_recursion_a_sub_assembly_is_a_link_and_its_parts_are_not_in_the_plan():
    plan = build_plan.plan(_castle())
    assert flat(plan) == ["ground", "east", "west", "gate"]


def test_recursively_a_sub_assembly_used_twice_is_put_together_once_before_the_first_link_that_adds_it():
    plan = build_plan.plan(_castle(), recursive=True)

    assert titles(plan) == [
        "//p:castle",
        [
            "ground",
            ["//p:tower (2)", ["stone", "Manufacture //p:window (2)", "window", "roof"]],
            "east",
            "west",
            "gate",
        ],
    ]
    tower = plan.children[1]
    assert (tower.type, tower.count) == (build_plan.ITEM_ASSEMBLY, 2)


def test_a_part_used_in_two_places_is_made_in_the_lowest_assembly_that_holds_both():
    window = made("//p:window")
    tower = assembly("//p:tower", bought("//p:stone", link="stone"), {**window, "link": "window"})
    castle = assembly(
        "//p:castle",
        bought("//p:ground", link="ground"),
        {**tower, "link": "east"},
        {**window, "link": "door-window"},
    )

    plan = build_plan.plan(castle, recursive=True)

    # One window in the tower and one in the castle: made once, two in all, at
    # the castle - before the tower, which is the first thing that needs one.
    assert titles(plan) == [
        "//p:castle",
        [
            "ground",
            "Manufacture //p:window (2)",
            ["//p:tower", ["stone", "window"]],
            "east",
            "door-window",
        ],
    ]


def test_a_sub_assembly_used_in_two_sub_assemblies_is_put_together_where_both_are():
    hinge = assembly("//p:hinge", bought("//p:pin", link="pin"), bought("//p:leaf", link="leaf"))
    door = assembly("//p:door", bought("//p:panel", link="panel"), {**hinge, "link": "hinge"})
    lid = assembly("//p:lid", bought("//p:top", link="top"), {**hinge, "link": "hinge"})
    box = assembly("//p:box", bought("//p:body", link="body"), {**door, "link": "door"}, {**lid, "link": "lid"})

    plan = build_plan.plan(box, recursive=True)

    assert titles(plan) == [
        "//p:box",
        [
            "body",
            ["//p:hinge (2)", ["pin", "leaf"]],
            ["//p:door", ["panel", "hinge"]],
            "door",
            ["//p:lid", ["top", "hinge"]],
            "lid",
        ],
    ]


def test_a_bought_sub_assembly_is_not_put_together_even_recursively():
    motor = assembly("//p:motor", bought("//p:rotor", link="rotor"), buy=True, link="motor")
    top = assembly("//p:top", bought("//p:frame", link="frame"), motor)

    assert flat(build_plan.plan(top, recursive=True)) == ["frame", "motor"]
    assert flat(build_plan.plan(top, {"//p:motor": BUILD}, recursive=True)) == ["frame", "//p:motor", "motor"]


def test_an_embedded_assembly_is_put_together_before_its_link_even_without_recursion():
    head = assembly(
        "//p:logo/head",
        bought("//p:half", link="half_1"),
        bought("//p:half", link="half_2"),
        embedded=True,
        link="head",
    )
    logo = assembly("//p:logo", bought("//p:bone", link="bone1"), bought("//p:bone", link="bone2"), head)

    assert titles(build_plan.plan(logo)) == [
        "//p:logo",
        ["bone1", "bone2", ["head", ["half_1", "half_2"]], "head"],
    ]


def test_every_item_has_an_id_of_its_own():
    plan = build_plan.plan(_castle(), recursive=True)
    ids = [item.id for item in plan.walk()]
    assert len(ids) == len(set(ids))


def test_the_plan_is_plain_data_on_the_wire():
    data = build_plan.plan(_castle(), recursive=True).to_data()
    assert data["type"] == "assembly"
    assert data["children"][1]["children"][1] == {
        "id": "make://p:window",
        "type": "manufacture",
        "name": "//p:window",
        "title": "Manufacture //p:window (2)",
        "count": 2,
        "kind": "part",
    }
    assert "node" not in data


def test_the_build_tab_is_for_trees_with_something_built_in_what_is_needed():
    assert not build_plan.has_build(bought("//p:screw"))
    assert build_plan.has_build(made("//p:panel"))
    # Bought whole: nothing inside it is needed, built or not.
    assert not build_plan.has_build(assembly("//p:top", made("//p:panel"), buy=True))


#
# What can be had at all
#


def test_something_that_can_be_neither_bought_nor_built_is_missing_and_never_built():
    assert build_plan.is_missing(node("//p:thing"))
    assert build_plan.is_missing({**node("//p:gone"), "missing": True})
    assert not build_plan.is_missing(bought("//p:screw"))
    assert not build_plan.is_missing(assembly("//p:top/head", embedded=True))


def test_one_not_meant_to_be_made_is_missing_whatever_it_could_otherwise_be():
    panel = {**made("//p:panel", buy=True), "manufacturable": False}

    assert build_plan.is_missing(panel)
    assert build_plan.effective_choice(panel, {"//p:panel": BUILD}) == BUY
    # So nothing is made of it, and nothing about making it is in the plan.
    top = assembly("//p:top", bought("//p:frame", link="frame"), {**panel, "link": "panel"})
    assert flat(build_plan.plan(top, {"//p:panel": BUILD})) == ["frame", "panel"]


#
# Against the examples: the tree says what 'pc test -f manufacturability' says
#


def _tree(ctx, kind, name, **options):
    import asyncio

    obj = ctx.get_assembly(name) if kind == "assembly" else ctx.get_part(name)
    tree, _index = asyncio.run(build_plan.tree_async(ctx, obj, **options))
    return tree


def _walk(tree):
    yield tree
    if tree.get("stock"):
        yield from _walk(tree["stock"])
    for child in tree.get("children") or []:
        yield from _walk(child)


def test_manufacturable_false_is_inherited_from_the_package_and_overridden_by_a_manufacturable_assembly():
    import partcad as pc

    ctx = pc.init("examples")

    # The examples say 'manufacturable: false' at their root, and this assembly
    # says nothing to the contrary: it is missing, and so is what is in it.
    embedded = _tree(ctx, "assembly", "//produce_assembly_assy:logo_embedded")
    assert embedded["manufacturable"] is False
    assert build_plan.is_missing(embedded)
    head = embedded["children"][2]
    assert head.get("embedded") and head["manufacturable"] is False

    # This one says it is manufacturable, and so is everything in it, whatever
    # the package its parts come from says about them on their own.
    logo = _tree(ctx, "assembly", "//produce_assembly_assy:logo")
    assert all(item["manufacturable"] for item in _walk(logo))

    # '--ignore-manufacturability' takes the first one as manufacturable too.
    forced = _tree(ctx, "assembly", "//produce_assembly_assy:logo_embedded", force_manufacturing=True)
    assert all(item["manufacturable"] for item in _walk(forced))


def test_a_part_whose_instructions_do_not_hold_up_cannot_be_built():
    import partcad as pc

    ctx = pc.init("examples")

    # Made by a CNC router, and saying nothing about how precisely: the test
    # refuses it with exactly this sentence.
    panel = _tree(ctx, "part", "//feature_cam:panel", force_manufacturing=True)
    assert panel["build"] is False
    assert panel["problems"] == ["No manufacturing tolerance is specified"]
    assert build_plan.is_missing(panel)


def test_every_line_says_which_file_it_is_made_from():
    """What the IDE opens when a line's name is clicked"""
    import os

    import partcad as pc

    ctx = pc.init("examples")
    logo = _tree(ctx, "assembly", "//produce_assembly_assy:logo")

    assert logo["source"].endswith(os.path.join("produce_assembly_assy", "logo.assy"))
    for line in _walk(logo):
        assert line["source"] is None or (os.path.isabs(line["source"]) and os.path.exists(line["source"]))
    assert any(line["source"] and line["kind"] == "part" for line in _walk(logo))
