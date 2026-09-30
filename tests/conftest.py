#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What every package's tests share, and nothing else.

Both of these are here rather than beside one package's tests because the
exposure they answer spans several of them: a test that writes out what
PartCAD's own container images are called is asserting what
`partcad_utils.container_image` answers when neither the tag nor the owner is
overridden, and CI overrides them on every run that rebuilt those images.

They differ in when they have to act. The first is enough where the reference is
built as the test runs; the second is for a module that builds it as it is
imported, which has to be imported again rather than adjusted in place.
"""

import importlib
import os
from unittest import mock

import pytest

from partcad_utils import container_image


@pytest.fixture
def no_image_tag_override(monkeypatch):
    """Run this test as an installed PartCAD does: with neither image override set.

    A test that spells out what PartCAD's own container images are *called* --
    `<image>:<release>` and nothing more -- is asserting the answer
    `container_image.image_tag` gives when nothing overrides it. CI overrides
    it: a run that rebuilt those images out of the commit under test exports
    the tag it published, and the `Pytest` job passes it through, because
    `tests/partcad/unit/test_part.py::test_part_example_kicad` starts the KiCad
    sandbox and has to reach the image *this* run built rather than the last
    release's.

    So such a test passes on every developer machine, where the variable is
    unset, and fails only on the runs that set it -- which are the runs nobody
    triggers until they are changing the images. Ask for this fixture wherever
    the release is written out as the tag.

    It is deliberately not autouse. Unsetting the variable for the whole suite
    would take it away from `test_part_example_kicad` too, and that test pulling
    the release's KiCad image on a run that published its own is the "manifest
    unknown" this whole mechanism exists to end.

    To reproduce a CI run that rebuilt the images::

        PC_CONTAINER_IMAGE_TAG=0.8.72-some-branch poetry run pytest tests

    And a fork's run, which redirects the owner as well::

        PC_CONTAINER_IMAGE_OWNER=someone poetry run pytest tests
    """
    monkeypatch.delenv(container_image.ENV_VAR, raising=False)
    # And the owner, which is the same exposure one segment to the left: a fork
    # that built its own images exports it, so a test spelling out
    # "ghcr.io/partcad/..." passes here and fails there. Both go together --
    # a test that wants "the release's image" wants the whole reference, not
    # the tag half of it.
    monkeypatch.delenv(container_image.ENV_VAR_OWNER, raising=False)


@pytest.fixture
def external_at_release():
    """`partcad_client.external`, re-imported as an installed PartCAD imports it.

    What `no_image_tag_override` does is not enough for this module, and the
    difference is easy to miss: `external` resolves the image reference **once,
    at import** -- `TOOLS` is built by `merge_tools()` as the module is read,
    and `builtin_tools()` caches what it found -- so unsetting a variable inside
    a test leaves the table carrying whatever the suite was started with. The
    module has to be read again with both variables already gone, which is what
    this yields.

    Both, for the reason the fixture above takes both: the tag and the owner are
    one reference, and a test wanting the release's image wants all of it.

    It restores the environment and reloads once more on the way out, in that
    order, so that the module the rest of the suite holds by name is the one it
    had: a module left carrying one test's environment is the next test's
    mystery. That ordering is also why this does not simply ask for
    `no_image_tag_override` -- a fixture is torn down before the fixtures it
    depends on, so the reload back would still run with the variables unset.

    `tests/partcad_utils/test_container_image.py` pins the other direction,
    where an override is set and this module has to follow it.
    """
    from partcad_client import external

    with mock.patch.dict(os.environ):
        os.environ.pop(container_image.ENV_VAR, None)
        os.environ.pop(container_image.ENV_VAR_OWNER, None)
        yield importlib.reload(external)

    importlib.reload(external)
