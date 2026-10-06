#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

import json
import os

from partcad_utils import garage


def test_the_file_of_an_object_is_named_after_it_and_after_nothing_else(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    path = garage.bvb_path("//pub/robots:arm/base")

    assert path == os.path.join(
        str(tmp_path), ".partcad", "garage", "default", "bvb", "%2F%2Fpub%2Frobots%3Aarm%2Fbase.json"
    )
    # The two characters a name is made of and no file name may hold are told
    # apart, so two objects can never share a file.
    assert garage.escape("//a:b") != garage.escape("//a/b")


def test_the_escaping_is_the_one_the_ide_writes():
    # 'encodeURIComponent' with !'()* escaped too: the same bytes as 'quote'.
    assert garage.escape("//pkg:part (v2)*!'~") == "%2F%2Fpkg%3Apart%20%28v2%29%2A%21%27~"
    assert garage.escape("//pkg:Ø") == "%2F%2Fpkg%3A%C3%98"


def test_choices_are_saved_and_read_back(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))

    garage.save_bvb("//pkg:top", {"//pkg:panel": "build", "//pkg:screw": "buy", "//pkg:odd": "steal"})

    assert garage.load_bvb("//pkg:top") == {"//pkg:panel": "build", "//pkg:screw": "buy"}
    assert garage.load_all_bvb() == {"//pkg:top": {"//pkg:panel": "build", "//pkg:screw": "buy"}}


def test_nothing_saved_and_something_unreadable_are_both_no_choices(monkeypatch, tmp_path):
    monkeypatch.setenv("HOME", str(tmp_path))
    assert garage.load_bvb("//pkg:top") == {}
    assert garage.load_all_bvb() == {}

    os.makedirs(garage.bvb_dir())
    with open(garage.bvb_path("//pkg:top"), "w") as f:
        f.write("{not json")
    with open(os.path.join(garage.bvb_dir(), "other.json"), "w") as f:
        json.dump(["not", "an", "object"], f)

    assert garage.load_bvb("//pkg:top") == {}
    assert garage.load_all_bvb() == {}
