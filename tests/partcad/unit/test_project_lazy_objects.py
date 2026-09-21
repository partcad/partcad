#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""A package creates the shapes somebody asks for, and not the others.

Loading a package used to create every sketch, part, assembly and scene it
declares, whatever the command was for. 'pc list assemblies -r' over a catalog
therefore ran a factory per part of every package it walked, to report the
assemblies; see 'Project.LAZY_OBJECT_KINDS'.
"""

import partcad as pc

PARTS = "//produce_part_cadquery_primitive"
ASSEMBLIES = "//produce_assembly_assy"


def test_loading_a_package_creates_nothing():
    ctx = pc.Context("examples")
    project = ctx.get_project(PARTS)
    assert project is not None
    for kind in ("sketch", "part", "assembly", "scene"):
        assert project.objects(kind) == {}


def test_reading_one_kind_creates_only_that_kind():
    ctx = pc.Context("examples")
    project = ctx.get_project(ASSEMBLIES)

    assert len(project.assemblies) > 0
    # The assemblies are made; the parts they are made of are not made with
    # them. An assembly resolves a part by name when it is built, which is what
    # makes this safe - and what a listing of assemblies never does.
    assert project.objects("part") == {}
    assert project.objects("sketch") == {}


def test_asking_for_one_object_creates_one_object():
    ctx = pc.Context("examples")
    project = ctx.get_project(PARTS)

    cube = project.get_part("cube")
    assert cube is not None
    # That one, and the alias its own declaration asks for ('aliases: ["box"]'),
    # which is part of creating it. Not the other eleven parts of the package.
    assert sorted(project.objects("part")) == ["box", "cube"]


def test_the_bulk_pass_keeps_what_is_already_there():
    """The object created by name is the object the listing then reports.

    'init_objects' would otherwise create a second one under a name that is
    taken, which 'register_object' refuses - and the refusal is recorded
    against the declaration, so the part would be reported as broken by the
    very command that had just built it.
    """
    ctx = pc.Context("examples")
    project = ctx.get_project(PARTS)

    cube = project.get_part("cube")
    assert project.parts["cube"] is cube
    assert "cube" not in project.broken_objects.get("part", {})


def test_declared_counts_do_not_depend_on_what_was_created():
    """'pc info' counts what the packages declare, not what somebody touched."""
    ctx = pc.Context("examples")
    project = ctx.get_project(PARTS)

    declared = ctx.stats_parts_declared
    assert declared == len(project.object_configs("part")) > 0
    assert project.objects("part") == {}  # counting created nothing

    project.get_part("cube")
    assert ctx.stats_parts_declared == declared


def test_one_by_name_and_the_bulk_pass_at_the_same_time():
    """Two threads, two ways in, and no object created twice.

    'get_part' creates the one part it was asked for and the bulk pass creates
    the rest, so the two now race for the same names. They go through one
    getter, which looks again under that object's own lock - without that, the
    bulk pass creates a second part under a name the other thread has just
    taken, 'register_object' refuses it, and the refusal is recorded against a
    declaration that is perfectly good.
    """
    import threading

    ctx = pc.Context("examples")
    project = ctx.get_project(PARTS)

    errors = []
    counts = []

    def by_name():
        try:
            assert project.get_part("cube") is not None
        except Exception as e:  # pragma: no cover - the failure is the report
            errors.append(repr(e))

    def in_bulk():
        try:
            counts.append(len(project.parts))
        except Exception as e:  # pragma: no cover
            errors.append(repr(e))

    threads = [threading.Thread(target=fn) for fn in (by_name, in_bulk) * 8]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join(timeout=60)

    assert [t for t in threads if t.is_alive()] == []  # nothing deadlocked
    assert errors == []
    assert len(set(counts)) == 1  # every bulk read saw the whole package
    assert project.broken_objects.get("part", {}) == {}
