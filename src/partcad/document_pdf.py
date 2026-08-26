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
import os

from . import document as pc_document
from . import logging as pc_logging
from . import sandbox_versions
from . import shape_envelope
from . import wrapper

# The paper the instruction book is printed on. A4 is the ISO default and what
# the rest of the world prints on; "letter" is accepted for North America.
DEFAULT_PAGE_SIZE = "A4"


async def render_pdf_async(ctx, document: pc_document.Document, path, page_size=DEFAULT_PAGE_SIZE):
    """Write 'document' to 'path' as a PDF file."""
    request = {
        "document": pc_document.to_data(document),
        "page_size": page_size,
    }
    request_serialized = shape_envelope.serialize(request)

    runtime = ctx.get_python_runtime(version="3.11")
    await runtime.ensure_async(sandbox_versions.REPORTLAB)
    await runtime.ensure_async(sandbox_versions.SVGLIB)

    command = [wrapper.get("render_pdf.py"), os.path.abspath(path)]
    exitcode, response_serialized, errors = await runtime.run_async(command, request_serialized)
    if exitcode != 0 and len(errors) == 0:
        errors = f"Failed to execute command '{' '.join(command)}' with exit code {exitcode}"
    if errors:
        pc_logging.error(errors)
        raise Exception(errors)

    response_lines = response_serialized.strip().splitlines()
    if not response_lines:
        raise Exception("Empty response from wrapper: %s" % command[0])
    result = shape_envelope.deserialize(response_lines[-1].strip())

    if not result.get("success", False):
        raise Exception("Failed to generate the PDF document: %s" % result.get("exception", "Unknown error"))

    return path


def render_pdf(ctx, document: pc_document.Document, path, page_size=DEFAULT_PAGE_SIZE):
    return asyncio.run(render_pdf_async(ctx, document, path, page_size))
