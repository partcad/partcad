#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""An enrich of a repository plugin that another package declares.

The way a user sets a plugin's parameters in a package of their own - a model
site's 'formats', say - without touching the package that declares it: an
enrich of the plugin, and a package served by the enrich. It is made from the
other package's declaration, so it is made once that package is loaded rather
than while its own is, and it runs as the other package's plugin - its script,
its sandbox, its directory - with the parameters the enrich gives it.
"""

import os
import textwrap

import partcad as pc

EXAMPLE = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", "..", "..", "examples"))


def test_an_enrich_of_another_packages_plugin_serves_a_package_with_its_own_parameters(tmp_path):
    (tmp_path / "partcad.yaml").write_text(textwrap.dedent("""
        dependencies:
          basic:
            type: local
            path: %s
          mine:
            type: external
            plugin: :my_csv
        repositories:
          my_csv:
            type: enrich
            source: //basic:csv
            with:
              filename: example.csv
        """ % os.path.join(EXAMPLE, "plugin_repository_basic")))
    ctx = pc.Context(str(tmp_path))

    # Nothing is broken by the enrich being declared before what it enriches is loaded.
    assert ctx.get_project("//").get_broken_object_reason("repository", "my_csv") is None
    # 'example.csv' is read where the plugin's script is, which is where it runs.
    assert sorted(ctx.get_project("//mine").object_names("part")) == ["bolt", "cube"]
    repository = ctx.get_project("//").get_repository("my_csv")
    assert repository is not None and repository.name.endswith(":my_csv")
