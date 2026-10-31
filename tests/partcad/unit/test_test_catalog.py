#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What each check of `pc test` is, written once for the IDE and the documentation.

The IDE's Test tab shows an entry of 'partcad.test.catalog' beside each verdict,
and 'docs/source/digital_thread/lifecycle/testing.rst' lists the same entries. Neither
may describe a check that does not exist, leave one out, or say something the
other does not.
"""

import os

import pytest

from partcad.test import catalog

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def test_every_check_pc_test_runs_has_an_entry_and_nothing_else_does():
    assert set(catalog.registered()) == set(catalog.TESTS)


def test_the_documentation_says_what_the_catalog_says():
    with open(os.path.join(ROOT, catalog.PAGE), encoding="utf-8") as stream:
        page = stream.read()
    assert catalog.page(page) == page, (
        "%s is out of date: run 'poetry run python -m partcad.test.catalog --write'" % catalog.PAGE
    )


def test_the_documentation_lists_the_checks_in_the_order_pc_test_runs_them():
    with open(os.path.join(ROOT, catalog.PAGE), encoding="utf-8") as stream:
        page = stream.read()
    positions = [page.index(".. _test-%s:" % name) for name in catalog.registered()]
    assert positions == sorted(positions)


@pytest.mark.parametrize("name", sorted(catalog.TESTS))
def test_every_entry_says_when_it_does_not_apply_and_what_to_do_when_it_fails(name):
    entry = catalog.describe(name)
    assert entry["title"] and entry["applies"]
    headings = [block["text"] for block in entry["blocks"] if block["type"] == "heading"]
    assert headings[:2] == [catalog.APPLIES, catalog.FAILS], headings
    # What it checks comes first, before any heading.
    assert entry["blocks"][0]["type"] in ("paragraph", "list")
    for block in entry["blocks"]:
        for text in [block.get("text", "")] + block.get("items", []):
            # Code spans are what the two readers interpret; an odd count is
            # one left open, which both would draw wrong.
            assert text.count("`") % 2 == 0, (name, text)


def test_the_markup_is_read_the_same_way_by_both_readers():
    blocks = catalog._blocks("""
A paragraph
over two lines with `code`.

### A heading

- an item
  continued
- another

```yaml
key: value
```
""")
    assert blocks == [
        {"type": "paragraph", "text": "A paragraph over two lines with `code`."},
        {"type": "heading", "text": "A heading"},
        {"type": "list", "items": ["an item continued", "another"]},
        {"type": "code", "language": "yaml", "text": "key: value"},
    ]
    assert catalog._rst_inline("a `b_` c_ d*e") == "a ``b_`` c\\_ d\\*e"


def test_a_check_with_no_entry_is_described_as_nothing():
    assert catalog.describe("no-such-check") is None
