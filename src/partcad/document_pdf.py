#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Composing a document (see document.py) into a PDF file.

The core has no library that can draw a PDF, the same way it has no library that
can build a shape: the libraries that can (reportlab, and svglib to place the
projections) live in the sandboxed runtimes, next to the CAD stack that produced
the illustrations. So the document travels there as plain data, and comes back
as a file.
"""

import asyncio
import hashlib
import json
import os

from . import cache_artifacts
from . import document as pc_document
from . import logging as pc_logging
from . import sandbox_versions, shape_envelope, wrapper
from .process_crash import command_failure

# The paper the instruction book is printed on. A4 is the ISO default and what
# the rest of the world prints on; "letter" is accepted for North America.
DEFAULT_PAGE_SIZE = "A4"

# The interpreter the PDF is composed in, and what is installed into it on top
# of the stack every sandbox carries. Named once, because they are both what is
# asked for and part of what a cached PDF is keyed on.
_PYTHON_VERSION = "3.11"
_DEPENDENCIES = (sandbox_versions.REPORTLAB, sandbox_versions.SVGLIB)


def _subject(data: dict) -> str:
    """What a PDF is composed from, as the subject of its cache key.

    The document as data, with every illustration named by its *content*
    rather than by its path: the pictures of an instruction book are drawn into
    a temporary directory that is a different one every time, and a path is
    neither what is drawn on the page nor the same on the next run.
    """

    def keyed(value):
        if isinstance(value, dict):
            found = {key: keyed(item) for key, item in value.items()}
            if value.get("type") == "images":
                found["images"] = [dict(image, path=_digest(image.get("path"))) for image in value.get("images") or []]
            return found
        if isinstance(value, list):
            return [keyed(item) for item in value]
        return value

    return cache_artifacts.content_key(json.dumps(keyed(data), sort_keys=True))


def _digest(path) -> str:
    """An illustration's content, as the digest it is keyed by."""
    if not path:
        return "none"
    try:
        with open(path, "rb") as f:
            return hashlib.sha256(f.read()).hexdigest()
    except OSError:
        # Drawn as a gap in the page, by the wrapper, and keyed as one.
        return "missing"


def _identity(path):
    try:
        stat = os.stat(path)
    except OSError:
        return None
    return (stat.st_ino, stat.st_size, stat.st_mtime_ns)


async def render_pdf_async(
    ctx,
    document: pc_document.Document,
    path,
    page_size=DEFAULT_PAGE_SIZE,
    reproducible: bool = False,
    cacheable: bool = True,
):
    """Write 'document' to 'path' as a PDF file.

    'reproducible' asks for the same bytes for the same book -- what every
    other file type's 'reproducible:' asks for, and what a document checked
    into a repository needs to be a baseline rather than a diff on every run.
    It is off by default for the same reason it is everywhere else: a book
    produced only to be read does not need it. See 'output.REPRODUCIBLE_KEY'.

    The same book asked for again is a read (see 'partcad.cache_artifacts'):
    keyed on its text, its tables, the content of every picture on its pages,
    the paper and the flag above, and composed again only when one of them
    changed. 'cacheable' False - a book about an object with `cache: false` -
    is composed every time.
    """
    path = os.path.abspath(path)
    data = pc_document.to_data(document)
    request = {
        "document": data,
        "page_size": page_size,
        "reproducible": bool(reproducible),
    }

    cache = getattr(ctx, "cache_artifacts", None)
    artifact = cache_artifacts.wrapper_hash(
        "%s#pdf" % (document.title or "document"),
        "render_pdf.py",
        _subject(data) if cacheable else None,
        _DEPENDENCIES,
        python_version=_PYTHON_VERSION,
        question={"page_size": page_size, "reproducible": bool(reproducible)},
    )
    pdf = {"pdf": path}
    if await cache_artifacts.restore_async(cache, artifact, files=pdf) is not None:
        return path

    request_serialized = shape_envelope.serialize(request)

    runtime = ctx.get_python_runtime(version=_PYTHON_VERSION)
    # Neither is in the sandbox's own environment, so the PDF is composed in a
    # layer over it (see 'runtime_python.base_requirements').
    session = runtime.get_session("pdf")
    for dependency in _DEPENDENCIES:
        await runtime.ensure_async(dependency, session=session)

    before = _identity(path)
    command = [wrapper.get("render_pdf.py"), path]
    exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized, session=session)
    if exitcode != 0 and len(errors) == 0:
        errors = command_failure(command, exitcode)
    if errors:
        pc_logging.error(errors)
        raise Exception(errors)

    if not response_serialized or not response_serialized.strip():
        raise Exception("Empty response from wrapper: %s" % command[0])
    result = shape_envelope.deserialize(response_serialized)

    if not result.get("success", False):
        raise Exception("Failed to generate the PDF document: %s" % result.get("exception", "Unknown error"))

    after = _identity(path)
    if after is not None and after != before:
        # Only a book this run wrote is remembered as its answer.
        await cache_artifacts.store_async(cache, artifact, {"success": True}, files=pdf)
    return path


def render_pdf(
    ctx,
    document: pc_document.Document,
    path,
    page_size=DEFAULT_PAGE_SIZE,
    reproducible: bool = False,
    cacheable: bool = True,
):
    return asyncio.run(render_pdf_async(ctx, document, path, page_size, reproducible=reproducible, cacheable=cacheable))
