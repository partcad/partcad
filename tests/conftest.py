#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What every package's tests share, and nothing else.

There is exactly one thing here so far, and it is here rather than beside one
package's tests because the exposure it answers spans three of them.
"""

import pytest

from partcad_utils import container_image


@pytest.fixture
def no_image_tag_override(monkeypatch):
    """Run this test as an installed PartCAD does: with no `PC_CONTAINER_IMAGE_TAG`.

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
    """
    monkeypatch.delenv(container_image.ENV_VAR, raising=False)
