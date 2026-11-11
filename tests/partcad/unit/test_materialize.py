#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A part whose geometry is what its machine makes, and the file that geometry is kept in.

    printed:
      manufacturing:
        method: additive
        source: design
        fff: {infill: 20%}

states no file: it is made on demand by following its manufacturing (the
'manufactured' type), `pc cam --materialize` writes it into `printed.brep` (or
the `step` or `sdf` file its `type:` names), and from then on that file is the
part, held to what the machine makes by the `materialize` check.

The machine itself is stubbed here, as 'test_additive.py' stubs the analysis:
what is tested is where the product goes and what is done with the answer.
What a route actually makes is 'test_cam_materialize.py's.
"""

import asyncio
import os

import pytest
import yaml

import partcad as pc
from partcad import shape_envelope
from partcad.part_config_manufacturing import IMPLIED_TYPE_KEY, MANUFACTURED_TYPE
from partcad.qual.basic.materialize import MaterializeTest

PACKAGE = {
    "name": "//test",
    "parts": {
        "design": {"type": "basic", "cuboid": [20, 10, 5]},
        "printed": {"manufacturing": {"method": "additive", "source": "design", "fff": {"infill": "20%"}}},
        "printed-step": {"type": "step", "manufacturing": {"method": "additive", "source": "design"}},
        "printed-sdf": {"type": "sdf", "manufacturing": {"method": "additive", "source": "design"}},
        "printed-here": {
            "path": "prints/here.brep",
            "manufacturing": {"method": "additive", "source": "design"},
        },
        # A geometry of its own that claims to be the print: a scan, say.
        "scanned": {
            "type": "basic",
            "cuboid": [20, 10, 5],
            "manufacturing": {"method": "additive", "source": "design"},
        },
        "molded": {"manufacturing": {"method": "forming", "source": "design", "mold": {"shrinkage": "1%"}}},
    },
}


def _context(root, files=()):
    (root / "partcad.yaml").write_text(yaml.safe_dump(PACKAGE))
    for name in files:
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("")
    return pc.Context(str(root))


@pytest.fixture
def ctx(tmp_path):
    return _context(tmp_path)


#
# What it is before and after it is materialized
#


def test_a_part_with_no_file_of_its_own_is_made_on_demand(ctx):
    part = ctx.get_part("//test:printed")
    assert part.config["type"] == MANUFACTURED_TYPE
    assert part.config[IMPLIED_TYPE_KEY] == "brep"
    assert part.desc == "design, as a 'fff' makes it"


def test_a_part_that_says_its_type_is_made_on_demand_until_its_file_is_written(ctx):
    part = ctx.get_part("//test:printed-step")
    assert part.config["type"] == MANUFACTURED_TYPE
    assert part.config[IMPLIED_TYPE_KEY] == "step"


def test_a_print_kept_as_an_sdf_is_meshed_at_half_a_layer(ctx):
    part = ctx.get_part("//test:printed-sdf")
    assert part.config[IMPLIED_TYPE_KEY] == "sdf"
    assert part.config["parameters"]["step"]["default"] == pytest.approx(0.1)


def test_once_written_the_file_is_the_part(tmp_path):
    context = _context(tmp_path, files=("printed.brep", "printed-step.step", "prints/here.brep"))
    printed = context.get_part("//test:printed")
    assert printed.config["type"] == "brep"
    assert printed.config["path"] == "printed.brep"
    assert context.get_part("//test:printed-step").config["type"] == "step"
    here = context.get_part("//test:printed-here")
    assert here.config["type"] == "brep"
    assert here.config["path"] == "prints/here.brep"


@pytest.mark.parametrize("written", [False, True])
def test_a_part_is_made_of_what_its_design_is_made_of_and_held_to_its_tolerance(tmp_path, written):
    """Whether it is made on demand or read from the file it was materialized into."""
    package = dict(PACKAGE)
    package["parts"] = dict(PACKAGE["parts"])
    package["parts"]["design"] = {
        "type": "basic",
        "cuboid": [20, 10, 5],
        "parameters": {
            "material": {"type": "string", "default": "//pub:pla"},
            "tolerance": {"type": "float", "default": 0.2},
        },
    }
    (tmp_path / "partcad.yaml").write_text(yaml.safe_dump(package))
    if written:
        (tmp_path / "printed.brep").write_text("")
        (tmp_path / "printed-step.step").write_text("")
    context = pc.Context(str(tmp_path))
    for name in ("printed", "printed-step", "printed-sdf"):
        part = context.get_part("//test:" + name)
        assert part is not None, name
        assert asyncio.run(part.get_mcft("material")) == "//pub:pla"
        assert asyncio.run(part.get_tolerance()) == pytest.approx(0.2)


#
# Writing it
#


def _stub_machine(monkeypatch, product=None, step=None, script=None):
    """Make every route answer with the given product, and record what was asked."""
    asked = []
    product = product or {shape_envelope.KEY_BREP: b"CASCADE Topology V3, (c) Open Cascade"}

    async def route(self, ctx, **kwargs):
        asked.append((self.name, kwargs))
        return {
            "product": product,
            "product_step": step if kwargs.get("representation") == "step" else None,
            "sdf_script": script if kwargs.get("representation") == "sdf" else None,
            "stats": {"volume": 1.0},
        }

    async def product_run(self, ctx, chosen, implementation, extra, output_dir, own_directory=False):
        asked.append((self.name, dict(extra, machine=chosen.kind)))
        return {"product": product, "stats": {}}

    monkeypatch.setattr(pc.shape.Shape, "route_async", route)
    monkeypatch.setattr(pc.shape.Shape, "_product_run_async", product_run)
    return asked


def test_a_print_is_written_to_its_name_as_brep(ctx, tmp_path, monkeypatch):
    asked = _stub_machine(monkeypatch)
    made = asyncio.run(ctx.get_part("//test:printed").materialize_async(ctx, write=True))
    assert made["written"] == str(tmp_path / "printed.brep")
    assert (tmp_path / "printed.brep").read_bytes().startswith(b"CASCADE Topology V3")
    # Asked to make it, on the printer it names.
    assert asked[0][1]["materialize"] is True


def test_a_print_is_written_where_its_path_says(ctx, tmp_path, monkeypatch):
    _stub_machine(monkeypatch)
    made = asyncio.run(ctx.get_part("//test:printed-here").materialize_async(ctx, write=True))
    assert made["written"] == str(tmp_path / "prints" / "here.brep")


def test_a_step_part_is_written_as_step(ctx, tmp_path, monkeypatch):
    asked = _stub_machine(monkeypatch, step="ISO-10303-21;\nEND-ISO-10303-21;\n")
    asyncio.run(ctx.get_part("//test:printed-step").materialize_async(ctx, write=True))
    assert (tmp_path / "printed-step.step").read_text().startswith("ISO-10303-21")
    # Asked for as STEP the first time: one route, not one for the shape and one for its text.
    assert [kwargs["representation"] for _name, kwargs in asked] == ["step"]


def test_an_sdf_part_is_written_as_its_script(ctx, tmp_path, monkeypatch):
    asked = _stub_machine(monkeypatch, script="show_object(print_)\n")
    asyncio.run(ctx.get_part("//test:printed-sdf").materialize_async(ctx, write=True))
    assert (tmp_path / "printed-sdf.py").read_text() == "show_object(print_)\n"
    assert [kwargs["representation"] for _name, kwargs in asked] == ["sdf"]


def test_a_product_that_cannot_be_written_leaves_the_old_one_as_it_was(ctx, tmp_path, monkeypatch):
    """The file is the old product or the new one, never part of either: the part is read from it."""
    (tmp_path / "printed.brep").write_bytes(b"the old print")
    _stub_machine(monkeypatch)

    class HalfWritten:
        """A file the disk fills up half way through."""

        def __init__(self, path, mode):
            self.file = open(path, mode)

        def __enter__(self):
            return self

        def __exit__(self, *exc):
            self.file.close()

        def write(self, data):
            self.file.write(data[: len(data) // 2])
            raise OSError("the disk is full")

    monkeypatch.setattr(pc.shape, "open", HalfWritten, raising=False)
    with pytest.raises(OSError, match="the disk is full"):
        asyncio.run(ctx.get_part("//test:printed").materialize_async(ctx, write=True))
    assert (tmp_path / "printed.brep").read_bytes() == b"the old print"
    # And nothing is left beside it.
    assert sorted(os.listdir(tmp_path)) == ["partcad.yaml", "printed.brep"]


def test_a_molding_is_asked_of_its_mold(ctx, tmp_path, monkeypatch):
    asked = _stub_machine(monkeypatch)
    asyncio.run(ctx.get_part("//test:molded").materialize_async(ctx, write=True))
    assert asked[0][1]["machine"] == "mold"
    assert (tmp_path / "molded.brep").exists()


def test_settings_tried_out_go_to_the_machine_and_not_into_the_declaration(ctx, monkeypatch):
    asked = _stub_machine(monkeypatch)
    part = ctx.get_part("//test:printed")
    asyncio.run(part.materialize_async(ctx, overrides={"infill": 0.6, "walls": None}))
    assert asked[0][1]["infill"] == 0.6
    assert "walls" not in asked[0][1]
    assert part.config["manufacturing"]["fff"] == {"infill": "20%"}


def test_a_part_whose_type_is_its_own_is_not_written_over(ctx, monkeypatch):
    _stub_machine(monkeypatch)
    with pytest.raises(pc.cam.CamConfigError, match="'basic' part"):
        asyncio.run(ctx.get_part("//test:scanned").materialize_async(ctx, write=True))


def test_a_part_made_some_other_way_is_not_materialized(ctx):
    with pytest.raises(pc.cam.CamConfigError, match="not made by following instructions"):
        asyncio.run(ctx.get_part("//test:design").materialize_async(ctx))


#
# The 'materialize' check
#


def _envelope(volume, bbox):
    return {
        shape_envelope.KEY_BREP: b"",
        shape_envelope.KEY_METADATA: {
            shape_envelope.METADATA_MEASUREMENTS: {
                shape_envelope.METADATA_VOLUME: volume,
                shape_envelope.METADATA_BBOX: list(bbox),
            }
        },
    }


BOX = (-10.0, -5.0, 0.0, 10.0, 5.0, 5.0)


def _arrange(monkeypatch, own, made, stats=None):
    async def wrapped(self, ctx):
        return own

    async def materialize(self, ctx, **kwargs):
        return {"product": made, "stats": stats or {}}

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    monkeypatch.setattr(pc.shape.Shape, "materialize_async", materialize)


def _verdict(ctx, name):
    return asyncio.run(MaterializeTest().test([], ctx, ctx.get_part("//test:" + name)))


def test_the_check_asks_only_a_part_with_a_geometry_of_its_own(ctx):
    check = MaterializeTest()
    assert "nothing to compare" in check.inapplicable(ctx.get_part("//test:printed"))
    assert "not made by following instructions" in check.inapplicable(ctx.get_part("//test:design"))
    assert check.inapplicable(ctx.get_part("//test:scanned")) is None


def test_a_materialized_part_is_asked_too(tmp_path):
    context = _context(tmp_path, files=("printed.brep",))
    assert MaterializeTest().inapplicable(context.get_part("//test:printed")) is None


def test_a_part_that_is_what_its_machine_makes_passes(ctx, monkeypatch):
    _arrange(monkeypatch, _envelope(500.0, BOX), _envelope(500.5, BOX))
    assert _verdict(ctx, "scanned") is MaterializeTest.TEST_PASSED


def test_a_part_the_wrong_size_fails(ctx, monkeypatch, caplog):
    larger = BOX[:3] + (12.0, 5.0, 5.0)
    _arrange(monkeypatch, _envelope(500.0, BOX), _envelope(560.0, larger))
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "scanned") is MaterializeTest.TEST_FAILED
    assert "its extent differs by 2.000 mm" in caplog.text


def test_a_part_the_right_size_and_the_wrong_weight_fails(ctx, monkeypatch, caplog):
    _arrange(monkeypatch, _envelope(1000.0, BOX), _envelope(400.0, BOX))
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "scanned") is MaterializeTest.TEST_FAILED
    assert "the machine makes 400.0 mm3" in caplog.text


def test_a_part_modelled_solid_is_what_its_print_looks_like(ctx, monkeypatch):
    """The print's sections stacked up: what a part drawn solid and printed with infill is the outside of."""
    _arrange(monkeypatch, _envelope(1000.0, BOX), _envelope(400.0, BOX), stats={"solid_volume": 1000.4})
    assert _verdict(ctx, "scanned") is MaterializeTest.TEST_PASSED


def test_a_machine_that_cannot_make_it_fails_the_check(ctx, monkeypatch, caplog):
    async def wrapped(self, ctx):
        return _envelope(1.0, BOX)

    async def broken(self, ctx, **kwargs):
        raise pc.cam.CamConfigError("no printer")

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", wrapped)
    monkeypatch.setattr(pc.shape.Shape, "materialize_async", broken)
    with caplog.at_level("ERROR"):
        assert _verdict(ctx, "scanned") is MaterializeTest.TEST_FAILED
    assert "could not be worked out: no printer" in caplog.text


def test_the_verdict_is_keyed_on_what_it_is_made_from_and_how(tmp_path):
    def suffix(fff):
        package = dict(PACKAGE)
        package["parts"] = dict(PACKAGE["parts"])
        package["parts"]["scanned"] = dict(PACKAGE["parts"]["scanned"])
        package["parts"]["scanned"]["manufacturing"] = {"method": "additive", "source": "design", "fff": fff}
        root = tmp_path / str(len(os.listdir(tmp_path)))
        root.mkdir()
        (root / "partcad.yaml").write_text(yaml.safe_dump(package))
        context = pc.Context(str(root))
        return asyncio.run(MaterializeTest().cache_key_suffix(context, context.get_part("//test:scanned")))

    sparse = suffix({"infill": "20%"})
    assert sparse.startswith(".materialize=")
    assert sparse != suffix({"infill": "40%"})


def test_a_cut_is_keyed_on_the_drawing_it_follows(tmp_path):
    """A cut along a sketch is routed from the sketch, so a changed outline is a different verdict."""

    def suffix(width):
        package = {
            "name": "//test",
            "sketches": {"outline": {"type": "basic", "rectangle": [width, 10]}},
            "parts": {
                "stock": {"type": "basic", "cuboid": [40, 30, 5]},
                "cut": {
                    "type": "basic",
                    "cuboid": [20, 10, 5],
                    "manufacturing": {
                        "method": "subtractive",
                        "source": "stock",
                        "instructions": "outline",
                        "cnc": {"diameter": 3},
                    },
                },
            },
        }
        root = tmp_path / str(len(os.listdir(tmp_path)))
        root.mkdir()
        (root / "partcad.yaml").write_text(yaml.safe_dump(package))
        context = pc.Context(str(root))
        return asyncio.run(MaterializeTest().cache_key_suffix(context, context.get_part("//test:cut")))

    assert suffix(20) != suffix(25)


def _made_from(tmp_path, design):
    """A scanned print of 'design', in a package of its own: '(context, part)'."""
    package = {
        "name": "//test",
        "parts": {
            "design": design,
            "scanned": {
                "type": "basic",
                "cuboid": [20, 10, 5],
                "manufacturing": {"method": "additive", "source": "design"},
            },
        },
    }
    root = tmp_path / str(len(os.listdir(tmp_path)))
    root.mkdir()
    (root / "partcad.yaml").write_text(yaml.safe_dump(package))
    context = pc.Context(str(root))
    return context, context.get_part("//test:scanned")


def test_nothing_made_from_a_design_that_keeps_no_key_is_keyed(tmp_path):
    """An edit of a 'cache: false' design leaves no key to tell it by, so nothing made from it may be kept."""
    from partcad.part_factory_manufactured import product_key_async

    kept = _made_from(tmp_path, {"type": "basic", "cuboid": [20, 10, 5]})
    assert asyncio.run(product_key_async(*kept))
    unkept = _made_from(tmp_path, {"type": "basic", "cuboid": [20, 10, 5], "cache": False})
    assert asyncio.run(product_key_async(*unkept)) is None
    # A design that is not there is keyed as missing: an answer, until it is added.
    missing = _made_from(tmp_path, {"type": "basic", "cuboid": [20, 10, 5]})
    missing[1].config["manufacturing"]["source"] = "nowhere"
    assert asyncio.run(product_key_async(*missing))


def test_the_verdict_on_a_print_of_a_design_that_keeps_no_key_is_not_kept(tmp_path, monkeypatch):
    _arrange(monkeypatch, _envelope(500.0, BOX), _envelope(500.5, BOX))
    context, part = _made_from(tmp_path, {"type": "basic", "cuboid": [20, 10, 5], "cache": False})
    test_ctx = {}
    assert asyncio.run(MaterializeTest().test([], context, part, test_ctx)) is MaterializeTest.TEST_PASSED
    assert test_ctx.get(MaterializeTest.NOT_CACHEABLE)

    context, part = _made_from(tmp_path, {"type": "basic", "cuboid": [20, 10, 5]})
    test_ctx = {}
    asyncio.run(MaterializeTest().test([], context, part, test_ctx))
    assert not test_ctx.get(MaterializeTest.NOT_CACHEABLE)


def test_a_cut_or_a_molding_is_keyed_on_every_setting_of_its_machine(tmp_path):
    """A tool diameter, a job every machine shares and a mold's shrinkage each change what is made."""

    def suffix(name, manufacturing):
        package = {
            "name": "//test",
            "sketches": {"outline": {"type": "basic", "rectangle": [20, 10]}},
            "parts": {
                "stock": {"type": "basic", "cuboid": [40, 30, 5]},
                name: {"type": "basic", "cuboid": [20, 10, 5], "manufacturing": manufacturing},
            },
        }
        root = tmp_path / str(len(os.listdir(tmp_path)))
        root.mkdir()
        (root / "partcad.yaml").write_text(yaml.safe_dump(package))
        context = pc.Context(str(root))
        return asyncio.run(MaterializeTest().cache_key_suffix(context, context.get_part("//test:" + name)))

    def cut(**section):
        return suffix("cut", dict({"method": "subtractive", "source": "stock", "instructions": "outline"}, **section))

    assert cut(cnc={"diameter": 3}) != cut(cnc={"diameter": 6})
    assert cut(cnc={"diameter": 3}, feed=1000) != cut(cnc={"diameter": 3}, feed=2000)

    def molded(shrinkage):
        return suffix("molded", {"method": "forming", "source": "stock", "mold": {"shrinkage": shrinkage}})

    assert molded("1%") != molded("2%")


def test_a_print_is_keyed_on_the_code_that_makes_it(tmp_path, monkeypatch):
    """A print an older route made is not this route's print."""
    from partcad import source_key

    def key(folder, implementation=None):
        package = dict(PACKAGE)
        package["parts"] = dict(PACKAGE["parts"])
        if implementation:
            package["parts"]["printed"] = {
                "manufacturing": {"method": "additive", "source": "design", "fff": {"implementation": implementation}}
            }
        root = tmp_path / folder
        root.mkdir()
        (root / "partcad.yaml").write_text(yaml.safe_dump(package))
        context = pc.Context(str(root))
        return asyncio.run(context.get_part("//test:printed").get_cache_key_async())

    builtin = key("a")
    assert key("b") == builtin
    # Another implementation is another maker...
    assert key("c", "//slicers:gcode") != builtin
    # ...and so is the same one with other sources.
    monkeypatch.setattr(source_key, "directory_key", lambda directory: "changed")
    assert key("d") != builtin


def test_a_print_kept_as_an_sdf_is_keyed_on_what_makes_it_and_not_on_its_script(tmp_path):
    """The script is written as the part is built, so a stale one on disk must not move the key."""
    from partcad import output

    def key(folder, infill="20%", stale=None):
        package = dict(PACKAGE)
        package["parts"] = dict(PACKAGE["parts"])
        package["parts"]["printed-sdf"] = {
            "type": "sdf",
            "manufacturing": {"method": "additive", "source": "design", "fff": {"infill": infill}},
        }
        root = tmp_path / folder
        root.mkdir()
        (root / "partcad.yaml").write_text(yaml.safe_dump(package))
        context = pc.Context(str(root))
        project = context.get_project("//test")
        if stale is not None:
            cache = os.path.join(output.package_cache_dir(context, project), "manufactured")
            os.makedirs(cache, exist_ok=True)
            with open(os.path.join(cache, "printed-sdf.py"), "w") as f:
                f.write(stale)
        part = context.get_part("//test:printed-sdf")
        found = asyncio.run(part.get_cache_key_async())
        assert part.get_cacheable()
        return found

    clean = key("a")
    assert clean is not None
    assert key("b", stale="show_object(an_older_print)\n") == clean
    assert key("c", infill="40%") != clean


def test_a_part_made_while_another_task_holds_its_lock_is_made(ctx, monkeypatch):
    """The deadlock a print kept as an SDF met in the daemon.

    Its build holds the part's lock and runs on a task of the pools
    ('Part.get_shape'), and routing it took the same lock again from there --
    waiting for itself for good. A part made on demand is routed into a
    directory of its own, which needs no lock: nobody else writes there.
    """
    asked = []

    async def design(self, ctx):
        return {shape_envelope.KEY_BREP: b"CASCADE Topology V3"}

    async def unlocked(self, ctx, impl, script, request, final_filepath):
        asked.append(final_filepath)
        with open(final_filepath, "w") as f:
            f.write("G21\nM30\n")
        return {"success": True, "product": {shape_envelope.KEY_BREP: b"deposit"}, "stats": {}}

    async def locked(self, *args, **kwargs):
        raise AssertionError("a route into a directory of its own took the part's lock")

    monkeypatch.setattr(pc.shape.Shape, "get_wrapped", design)
    monkeypatch.setattr(pc.shape.Shape, "_run_implementation_locked", unlocked)
    monkeypatch.setattr(pc.shape.Shape, "_run_implementation_async", locked)
    part = ctx.get_part("//test:printed")

    async def scenario():
        held = asyncio.Event()
        done = asyncio.Event()

        async def build():
            async with part.locked():
                held.set()
                await done.wait()

        holder = asyncio.create_task(build())
        await held.wait()
        try:
            return await asyncio.wait_for(part.materialize_async(ctx), timeout=60)
        finally:
            done.set()
            await holder

    made = asyncio.run(scenario())
    assert made["product"][shape_envelope.KEY_BREP] == b"deposit"
    assert len(asked) == 1
