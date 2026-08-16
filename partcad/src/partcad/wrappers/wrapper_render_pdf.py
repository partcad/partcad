#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# This script is executed within a python runtime environment: it is where the
# libraries that can draw a PDF are installed, next to the CAD stack that
# rendered the illustrations it places. It receives a document as plain data
# (see document.py) and lays it out on paper.
#
# Note that this wrapper touches no geometry at all - the pictures reach it as
# SVG files that have already been rendered.

import os
import re
import sys

from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4, letter
from reportlab.lib.utils import simpleSplit
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdf_canvas

import svglib.svglib as svglib

sys.path.append(os.path.dirname(__file__))
import wrapper_common

PAGE_SIZES = {"A4": A4, "letter": letter}

MARGIN = 42.0  # ~15mm
FONT = "Helvetica"
FONT_BOLD = "Helvetica-Bold"
FONT_ITALIC = "Helvetica-Oblique"

# Font size per heading level; anything deeper is set at body size.
HEADING_SIZES = {1: 22, 2: 16, 3: 12}
BODY_SIZE = 10
SMALL_SIZE = 8
LINE_SPACING = 1.35
LINK_COLOR = (0.1, 0.35, 0.7)

# The narrowest a table column is ever wrapped into.
MIN_WRAP_WIDTH = 24.0


class Composer:
    """Lays blocks out on paper, breaking to a new page when one runs out."""

    def __init__(self, path, page_size, footer=None):
        self.width, self.height = page_size
        self.canvas = pdf_canvas.Canvas(path, pagesize=(self.width, self.height))
        self.footer = footer
        self.page_number = 0
        self._start_page()

    #
    # Page handling
    #

    def _start_page(self):
        self.page_number += 1
        self.y = self.height - MARGIN

    def _finish_page(self):
        self.canvas.setFont(FONT_ITALIC, SMALL_SIZE)
        self.canvas.setFillGray(0.45)
        if self.footer:
            self.canvas.drawString(MARGIN, MARGIN / 2, self.footer)
        self.canvas.drawRightString(self.width - MARGIN, MARGIN / 2, str(self.page_number))
        self.canvas.setFillGray(0.0)
        self.canvas.showPage()

    def new_page(self):
        self._finish_page()
        self._start_page()

    def save(self):
        self._finish_page()
        self.canvas.save()

    @property
    def content_width(self):
        return self.width - 2 * MARGIN

    def space(self, height):
        """Make room for something 'height' tall, breaking the page if needed."""
        if self.y - height < MARGIN and self.y < self.height - MARGIN:
            self.new_page()

    #
    # Blocks
    #

    def block(self, block):
        kind = block.get("type")
        if kind == "heading":
            self.heading(block)
        elif kind == "paragraph":
            self.paragraph(block["text"])
        elif kind == "properties":
            self.properties(block["items"])
        elif kind == "images":
            self.images(block)
        elif kind == "table":
            self.table(block)
        elif kind == "links":
            self.links(block["items"])

    def heading(self, block):
        size = HEADING_SIZES.get(block.get("level", 1), BODY_SIZE)
        self.space(size * 2.4)
        self.y -= size * LINE_SPACING
        self.canvas.setFont(FONT_BOLD, size)
        text = block["text"]
        url = block.get("url")
        if url:
            self.canvas.setFillColorRGB(*LINK_COLOR)
        self.canvas.drawString(MARGIN, self.y, text)
        if url:
            self.canvas.linkURL(
                url,
                (MARGIN, self.y - 2, MARGIN + stringWidth(text, FONT_BOLD, size), self.y + size),
                relative=0,
            )
            self.canvas.setFillGray(0.0)
        self.y -= size * 0.5

    def paragraph(self, text, size=BODY_SIZE, font=FONT):
        for line in text.split("\n"):
            for wrapped in simpleSplit(line, font, size, self.content_width) or [""]:
                self.space(size * LINE_SPACING)
                self.y -= size * LINE_SPACING
                self.canvas.setFont(font, size)
                self.canvas.drawString(MARGIN, self.y, wrapped)
        self.y -= size * 0.5

    def properties(self, items):
        size = BODY_SIZE
        label_width = max([stringWidth(str(label) + ":  ", FONT_BOLD, size) for label, _ in items] or [0])
        for label, value in items:
            self.space(size * LINE_SPACING)
            self.y -= size * LINE_SPACING
            self.canvas.setFont(FONT_BOLD, size)
            self.canvas.drawString(MARGIN, self.y, "%s:" % label)
            self.canvas.setFont(FONT, size)
            self.canvas.drawString(MARGIN + label_width, self.y, str(value))
        self.y -= size * 0.5

    def links(self, items):
        size = BODY_SIZE
        for text, url in items:
            self.space(size * 1.8)
            self.y -= size * 1.8
            self.canvas.setFont(FONT, size)
            self.canvas.setFillColorRGB(*LINK_COLOR)
            self.canvas.drawString(MARGIN, self.y, text)
            width = stringWidth(text, FONT, size)
            self.canvas.linkURL(url, (MARGIN, self.y - 2, MARGIN + width, self.y + size), relative=0)
            self.canvas.setFillGray(0.45)
            self.canvas.setFont(FONT_ITALIC, SMALL_SIZE)
            self.canvas.drawString(MARGIN + width + 8, self.y, url)
            self.canvas.setFillGray(0.0)
        self.y -= size * 0.5

    def images(self, block):
        images = block.get("images") or []
        drawings = [(image, _load_image(image.get("path"))) for image in images]
        drawings = [(image, drawing) for image, drawing in drawings if drawing is not None]
        if not drawings:
            return

        box_width = (self.content_width - 12 * (len(drawings) - 1)) / len(drawings)

        # How much the captions actually take, not a guess of two lines: a
        # caption is wrapped into the width of its own picture, and one that
        # wraps further than the room reserved for it would be drawn past the
        # bottom margin, over whatever comes next.
        caption_lines = max(
            (
                len(simpleSplit(image["caption"], FONT_ITALIC, SMALL_SIZE, box_width))
                for image, _ in drawings
                if image.get("caption")
            ),
            default=0,
        )
        caption_height = caption_lines * SMALL_SIZE * 1.2
        box_height = self.height * float(block.get("height", 0.4)) - caption_height

        # An illustration is not worth splitting across two pages: if what is
        # left of this one cannot hold it, it starts the next one.
        self.space(box_height + caption_height + 12)
        top = self.y

        x = MARGIN
        lowest = top
        for image, drawing in drawings:
            if not drawing.width or not drawing.height:
                # An empty or degenerate viewport. Nothing to place, and nothing
                # to divide by either.
                sys.stderr.write("Skipping an illustration of no size: %s\n" % image.get("path"))
                continue
            scale = min(box_width / drawing.width, box_height / drawing.height)
            width, height = drawing.width * scale, drawing.height * scale
            drawing.scale(scale, scale)
            drawing.width, drawing.height = width, height
            offset = x + (box_width - width) / 2
            renderPDF.draw(drawing, self.canvas, offset, top - height)

            bottom = top - height
            if image.get("caption"):
                self.canvas.setFont(FONT_ITALIC, SMALL_SIZE)
                self.canvas.setFillGray(0.35)
                for line in simpleSplit(image["caption"], FONT_ITALIC, SMALL_SIZE, box_width):
                    bottom -= SMALL_SIZE * 1.2
                    self.canvas.drawCentredString(x + box_width / 2, bottom, line)
                self.canvas.setFillGray(0.0)
            lowest = min(lowest, bottom)
            x += box_width + 12

        self.y = lowest - 12

    def table(self, block):
        columns = block.get("columns") or []
        aligns = block.get("aligns") or ["left"] * len(columns)
        rows = block.get("rows") or []
        if not columns:
            return

        widths = _column_widths(columns, rows, self.content_width)

        def draw_header():
            self.space(BODY_SIZE * 2)
            self.y -= BODY_SIZE * LINE_SPACING
            self._row(columns, widths, aligns, FONT_BOLD)
            self.canvas.setStrokeGray(0.6)
            self.canvas.line(MARGIN, self.y - 3, self.width - MARGIN, self.y - 3)
            self.y -= 6

        draw_header()
        for row in rows:
            # A row with more cells than there are columns keeps them, as the
            # markdown and the HTML renderers do: 'zip(row, widths)' would drop
            # them, and a bill of materials that loses a value on paper alone is
            # worse than one that looks crowded.
            row_widths, row_aligns = _fit_row(row, widths, aligns)
            # 'max(..., MIN_WRAP_WIDTH)': a column squeezed down to nothing by a
            # single very long value would otherwise be asked to wrap text into
            # zero width, which no line ever fits into.
            cells = [
                simpleSplit(str(cell), FONT, BODY_SIZE, max(width - 8, MIN_WRAP_WIDTH)) or [""]
                for cell, width in zip(row, row_widths)
            ]
            height = max(len(lines) for lines in cells) * BODY_SIZE * LINE_SPACING
            if self.y - height < MARGIN:
                # A table that outgrows the page continues on the next one, under
                # a repeated header: a column of numbers with no headings on it
                # is not a bill of materials.
                self.new_page()
                draw_header()
            for index in range(max(len(lines) for lines in cells)):
                self.y -= BODY_SIZE * LINE_SPACING
                self._row(
                    [lines[index] if index < len(lines) else "" for lines in cells],
                    row_widths,
                    row_aligns,
                    FONT,
                )
        self.y -= BODY_SIZE

    def _row(self, cells, widths, aligns, font):
        self.canvas.setFont(font, BODY_SIZE)
        x = MARGIN
        for cell, width, align in zip(cells, widths, aligns):
            if align == "right":
                self.canvas.drawRightString(x + width - 8, self.y, str(cell))
            else:
                self.canvas.drawString(x, self.y, str(cell))
            x += width


def _fit_row(row, widths, aligns):
    """Widths and alignments covering every cell of a row.

    A row is normally exactly as wide as the table's columns. One that is wider
    borrows the last column's width for the cells beyond them, so they are drawn
    rather than dropped.
    """
    if len(row) <= len(widths):
        return widths, aligns
    extra = len(row) - len(widths)
    return list(widths) + [widths[-1]] * extra, list(aligns) + ["left"] * extra


def _column_widths(columns, rows, available):
    """Column widths proportional to what each column has to say."""
    natural = []
    for index, column in enumerate(columns):
        widest = stringWidth(str(column), FONT_BOLD, BODY_SIZE)
        for row in rows:
            if index < len(row):
                widest = max(widest, stringWidth(str(row[index]), FONT, BODY_SIZE))
        natural.append(widest + 12)

    total = sum(natural)
    if total <= available:
        # Give the slack to the last column, so the table spans the page.
        natural[-1] += available - total
        return natural
    return [width * available / total for width in natural]


def _load_image(path):
    """The drawable form of an illustration, or None if it cannot be read.

    A picture that cannot be read is left out rather than allowed to fail the
    whole book, but it is reported: a page silently missing its illustration is
    not something the reader of the PDF can diagnose. The wrapper exits zero, so
    this reaches the caller as a warning (see runtime_python.run_async_onced).
    """
    if not path or not os.path.exists(path):
        return None
    try:
        return svglib.svg2rlg(path)
    except Exception as e:
        sys.stderr.write("Failed to read the illustration %s: %s\n" % (path, e))
        return None


def process(path, request):
    try:
        document = request["document"]
        page_size = PAGE_SIZES.get(request.get("page_size"), A4)

        footer = document.get("footer")
        # The footer is markdown in the model; on paper there is nowhere for a
        # link to go, so only what it says is kept.
        if footer:
            footer = _plain(footer)

        composer = Composer(path, page_size, footer)
        for number, page in enumerate(document.get("pages") or []):
            if number > 0:
                composer.new_page()
            for block in page.get("blocks") or []:
                composer.block(block)
        composer.save()

        return {"success": True, "exception": None}
    except Exception as e:
        wrapper_common.handle_exception(e)
        return {"success": False, "exception": str(e)}


def _plain(text):
    """Markdown links reduced to their text: '[PartCAD](url)' -> 'PartCAD'."""
    return re.sub(r"\[([^\]]*)\]\(([^)]*)\)", r"\1", text)


if __name__ == "__main__":
    path, request = wrapper_common.handle_input()
    response = process(path, request)
    wrapper_common.handle_output(response)
