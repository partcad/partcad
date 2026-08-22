#!/usr/bin/env python3
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Tests for the 'fileFrom'/'fileUrl' constraints in the configuration schema.

'pc lint' validates 'partcad.yaml' against this schema, but only for packages
that load: a configuration broken badly enough to fail the object factories
never gets that far (see 'test_file.py' for what the loader reports instead).
These tests go at the schema directly, so every combination is covered
regardless of what the loader does with it.
"""

import jsonschema
import jsonschema.exceptions
import pytest

from partcad.lint.all import get_partcad_schema


def validate(config):
    jsonschema.validate(instance=config, schema=get_partcad_schema())


def failure(config):
    with pytest.raises(jsonschema.exceptions.ValidationError) as err:
        validate(config)
    return err.value


# An object of each kind that carries a source file, in the shortest form that
# declares where to pull that file from.
FILE_BACKED = {
    "parts": {"bolt": {"type": "step"}},
    "sketches": {"outline": {"type": "dxf"}},
    "assemblies": {"rig": {"type": "assy"}},
}


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_file_from_url(kind):
    """'fileFrom: url' plus 'fileUrl' is accepted for every file-backed object"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    config = dict(config, fileFrom="url", fileUrl="https://example.com/vendor/%s" % name)
    validate({kind: {name: config}})


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_file_from_without_file_url(kind):
    """'fileFrom' without 'fileUrl' is rejected, and the object is named"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    error = failure({kind: {name: dict(config, fileFrom="url")}})
    assert error.json_path == "$.%s.%s" % (kind, name)
    assert error.message == "'fileUrl' is a dependency of 'fileFrom'"


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_file_url_without_file_from(kind):
    """'fileUrl' without 'fileFrom' is rejected, and the object is named"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    error = failure({kind: {name: dict(config, fileUrl="https://example.com/vendor/%s" % name)}})
    assert error.json_path == "$.%s.%s" % (kind, name)
    assert error.message == "'fileFrom' is a dependency of 'fileUrl'"


@pytest.mark.parametrize("kind", FILE_BACKED.keys())
def test_schema_unsupported_file_from(kind):
    """'url' is the only source a file can be pulled from so far"""
    name, config = next(iter(FILE_BACKED[kind].items()))
    config = dict(config, fileFrom="ftp", fileUrl="https://example.com/vendor/%s" % name)
    error = failure({kind: {name: config}})
    assert error.json_path == "$.%s.%s.fileFrom" % (kind, name)
    assert "'ftp' is not one of ['url']" in error.message
