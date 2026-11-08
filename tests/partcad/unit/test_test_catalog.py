#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What each built-in qualification check is, written once for the IDE and the documentation.

The IDE's Qualification tabs show an entry of 'partcad.qual.catalog' beside each
verdict, and 'docs/source/digital_thread/lifecycle/qualification_tests.rst'
lists the same entries, a section per subtype. Neither may describe a check that
does not exist, leave one out, or say something the other does not.
"""

import os

import pytest

from partcad.qual import catalog
from partcad.qual.config import SUBTYPES

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", ".."))


def test_every_check_pc_test_runs_has_an_entry_and_nothing_else_does():
    assert set(catalog.registered()) == set(catalog.TESTS)


def test_the_documentation_says_what_the_catalog_says():
    with open(os.path.join(ROOT, catalog.PAGE), encoding="utf-8") as stream:
        page = stream.read()
    assert catalog.page(page) == page, (
        "%s is out of date: run 'poetry run python -m partcad.qual.catalog --write'" % catalog.PAGE
    )


def test_the_documentation_lists_the_checks_by_subtype_in_the_order_they_run():
    with open(os.path.join(ROOT, catalog.PAGE), encoding="utf-8") as stream:
        page = stream.read()
    subtypes = catalog.registered_subtypes()
    names = sorted(catalog.registered(), key=lambda name: SUBTYPES.index(subtypes[name]))
    positions = [page.index(".. _test-%s:" % name) for name in names]
    assert positions == sorted(positions)
    # And each one under the heading of its own subtype.
    for name in names:
        heading = page.rindex(".. _qual-", 0, page.index(".. _test-%s:" % name))
        assert page.startswith(".. _qual-%s:" % subtypes[name], heading), name


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
