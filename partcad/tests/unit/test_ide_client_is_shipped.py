#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'partcad_ide_client' ships inside the 'partcad' wheel. This checks it still can.

The package's source lives in the `partcad-ide-client` component directory and
reaches `partcad/src` as a relative symlink, which is what puts it in the wheel
and the sdist (setuptools dereferences it into real files). That symlink is
load-bearing and can be lost without anything complaining: a checkout with
`core.symlinks=false` -- Git for Windows' default unless Developer Mode is on --
writes it as a small text file naming the target, `packages.find` then finds no
package there, and `python -m build` reports success while producing a wheel with
no `partcad_ide_client` in it.

So the failure this file exists to catch is a *silent* one, and the check has to
be on the layout rather than on the import: `import partcad_ide_client` alone
would keep passing on a machine that has it installed some other way.
"""

import pathlib

REPO_ROOT = pathlib.Path(__file__).resolve().parents[3]
LINK = REPO_ROOT / "partcad" / "src" / "partcad_ide_client"
COMPONENT = REPO_ROOT / "partcad-ide-client" / "src" / "partcad_ide_client"


def test_the_component_source_is_reachable_from_the_partcad_package_dir():
    """Whatever `packages.find` sees under 'partcad/src' is what the wheel gets."""
    assert LINK.is_dir(), (
        "%s is not a directory. If it is a small text file naming a path, this checkout did not "
        "materialise the symlink (Git for Windows does that with core.symlinks=false) and the "
        "'partcad' wheel built here will be missing 'partcad_ide_client' -- without any build error. "
        "Re-clone with symlinks enabled, or 'git config core.symlinks true' and check the file out again." % LINK
    )
    assert (LINK / "__init__.py").is_file()
    assert LINK.resolve() == COMPONENT.resolve(), "%s should resolve to %s" % (LINK, COMPONENT)


def test_the_two_paths_are_the_same_file():
    """A copy instead of a link would drift silently; make it one file, not two."""
    assert (LINK / "protocol.py").read_bytes() == (COMPONENT / "protocol.py").read_bytes()


def test_it_is_importable_and_versioned_with_partcad():
    """The monorepo releases everything under one version, this package included.

    Imported here rather than at module scope on purpose: a lost symlink makes
    this a collection error, and a collection error aborts the run (pytest is
    driven with '-x') before the two checks above can say what went wrong.
    """
    import partcad
    import partcad_ide_client

    assert partcad_ide_client.__version__ == partcad.__version__
