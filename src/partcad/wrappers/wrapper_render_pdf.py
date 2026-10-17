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

import svglib.svglib as svglib
from reportlab.graphics import renderPDF
from reportlab.lib.pagesizes import A4, letter
from reportlab.pdfbase.pdfmetrics import stringWidth
from reportlab.pdfgen import canvas as pdf_canvas

sys.path.append(os.path.dirname(__file__))
import wrapper_common
from wrapper_layout import fit_row
from wrapper_layout import wrap as layout_wrap

# What this wrapper reports for what it produces (see 'partcad.code_version'):
# raise it with any change that changes that, and everything it produced
# before is produced again.
CACHE_VERSION = 2

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

# The most of the page a column is widened to so that its longest word fits.
MAX_WORD_SHARE = 0.4

# The kicker over a heading, and the box a row of parts is set in.
KICKER_SIZE = 9
BOX_PADDING = 8.0
BOX_GRAY = 0.96
BOX_LINE_GRAY = 0.75


class Composer:
    """Lays blocks out on paper, breaking to a new page when one runs out."""

    def __init__(self, path, page_size, footer=None, reproducible=False):
        self.width, self.height = page_size
        # 'invariant' is what makes the same book the same file. Without it
        # reportlab writes the wall clock into '/CreationDate' and '/ModDate'
        # and a random '/ID', so two runs a second apart differ in bytes while
        # saying the same thing -- which is the one thing a checked-in document
        # may not do (see 'output.REPRODUCIBLE_KEY'). It settles nothing else:
        # the illustrations arrive as SVGs that were already rendered, and
        # whether *those* are reproducible is the projection's business.
        self.canvas = pdf_canvas.Canvas(path, pagesize=(self.width, self.height), invariant=1 if reproducible else 0)
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
            self.styled_paragraph(block)
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
        text = block["text"]
        # A heading is as wide as the page and no wider: a name too long for
        # one line goes on to the next rather than off the edge of the paper.
        lines = wrap(text, FONT_BOLD, size, self.content_width)
        kicker = block.get("kicker")
        self.space(size * (1.0 + LINE_SPACING * len(lines)) + (KICKER_SIZE * 1.6 if kicker else 0))
        if kicker:
            self.y -= KICKER_SIZE * 1.3
            self.canvas.setFont(FONT_BOLD, KICKER_SIZE)
            self.canvas.setFillGray(0.45)
            for line in wrap(kicker.upper(), FONT_BOLD, KICKER_SIZE, self.content_width)[:1]:
                self.canvas.drawString(MARGIN, self.y, line)
            self.canvas.setFillGray(0.0)
        url = block.get("url")
        for line in lines:
            self.y -= size * LINE_SPACING
            self.canvas.setFont(FONT_BOLD, size)
            if url:
                self.canvas.setFillColorRGB(*LINK_COLOR)
            self.canvas.drawString(MARGIN, self.y, line)
            if url:
                self.canvas.linkURL(
                    url,
                    (MARGIN, self.y - 2, MARGIN + stringWidth(line, FONT_BOLD, size), self.y + size),
                    relative=0,
                )
                self.canvas.setFillGray(0.0)
        self.y -= size * 0.5

    def paragraph(self, text, size=BODY_SIZE, font=FONT, gray=0.0):
        for line in text.split("\n"):
            for wrapped in wrap(line, font, size, self.content_width) or [""]:
                self.space(size * LINE_SPACING)
                self.y -= size * LINE_SPACING
                self.canvas.setFont(font, size)
                self.canvas.setFillGray(gray)
                self.canvas.drawString(MARGIN, self.y, wrapped)
        self.canvas.setFillGray(0.0)
        self.y -= size * 0.5

    def styled_paragraph(self, block):
        """A paragraph in the style it says: a detail is small and grey, a note slanted."""
        style = block.get("style")
        if style == "detail":
            self.paragraph(block["text"], size=SMALL_SIZE, font=FONT, gray=0.4)
        elif style == "note":
            self.paragraph(block["text"], font=FONT_ITALIC)
        else:
            self.paragraph(block["text"])

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

        boxed = bool(block.get("boxed"))
        title = block.get("title") if boxed else None
        # A boxed row is set in from the margins by the padding of its box, and
        # its pictures are no wider than a quarter of the page each: it is a
        # row of small parts, and a part drawn across the page is not small.
        inset = BOX_PADDING if boxed else 0.0
        available = self.content_width - 2 * inset
        box_width = (available - 12 * (len(drawings) - 1)) / len(drawings)
        if boxed:
            box_width = min(box_width, self.content_width / 4.0)

        # How much the captions actually take, not a guess of two lines: a
        # caption is wrapped into the width of its own picture, and one that
        # wraps further than the room reserved for it would be drawn past the
        # bottom margin, over whatever comes next.
        caption_lines = max(
            (
                len(wrap(image["caption"], FONT_ITALIC, SMALL_SIZE, box_width))
                for image, _ in drawings
                if image.get("caption")
            ),
            default=0,
        )
        caption_height = caption_lines * SMALL_SIZE * 1.2
        box_height = self.height * float(block.get("height", 0.4)) - caption_height
        title_height = BODY_SIZE * 1.6 if title else 0.0

        # An illustration is not worth splitting across two pages: if what is
        # left of this one cannot hold it, it starts the next one.
        self.space(box_height + caption_height + title_height + 12 + 2 * inset)
        if boxed:
            frame_top = self.y - 4
            frame_height = box_height + caption_height + title_height + 2 * inset
            self.canvas.setFillGray(BOX_GRAY)
            self.canvas.setStrokeGray(BOX_LINE_GRAY)
            self.canvas.roundRect(
                MARGIN, frame_top - frame_height, self.content_width, frame_height, 6, stroke=1, fill=1
            )
            self.canvas.setFillGray(0.0)
            self.y = frame_top - inset
            if title:
                self.y -= BODY_SIZE
                self.canvas.setFont(FONT_BOLD, BODY_SIZE)
                self.canvas.drawString(MARGIN + inset, self.y, title)
                self.y -= BODY_SIZE * 0.6
        top = self.y

        x = MARGIN + inset
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
                for line in wrap(image["caption"], FONT_ITALIC, SMALL_SIZE, box_width):
                    bottom -= SMALL_SIZE * 1.2
                    self.canvas.drawCentredString(x + box_width / 2, bottom, line)
                self.canvas.setFillGray(0.0)
            lowest = min(lowest, bottom)
            x += box_width + 12

        self.y = lowest - 12 - inset

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
            row_widths, row_aligns = fit_row(row, widths, aligns)
            # 'max(..., MIN_WRAP_WIDTH)': a column squeezed down to nothing by a
            # single very long value would otherwise be asked to wrap text into
            # zero width, which no line ever fits into.
            cells = [
                wrap(str(cell), FONT, BODY_SIZE, max(width - 8, MIN_WRAP_WIDTH)) or [""]
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


def wrap(text, font, size, width):
    """'text' broken into lines no wider than 'width' when set in 'font' at 'size' (see 'wrapper_layout.wrap')."""
    return layout_wrap(text, width, lambda piece: stringWidth(piece, font, size))


def _column_widths(columns, rows, available):
    """Column widths proportional to what each column has to say.

    Every column gets at least its longest word - a name with no spaces in it,
    a number - up to a share of the page ('MAX_WORD_SHARE'), and what is left
    is shared out by how much more each column has to say. Shared out in
    proportion to the whole text alone, a column of long descriptions took the
    page and left a column of names too narrow for any of them.
    """
    natural = []
    least = []
    for index, column in enumerate(columns):
        widest = stringWidth(str(column), FONT_BOLD, BODY_SIZE)
        word = max([stringWidth(part, FONT_BOLD, BODY_SIZE) for part in str(column).split()] or [0])
        for row in rows:
            if index < len(row):
                widest = max(widest, stringWidth(str(row[index]), FONT, BODY_SIZE))
                word = max([word] + [stringWidth(part, FONT, BODY_SIZE) for part in str(row[index]).split()])
        natural.append(widest + 12)
        least.append(min(word + 12, available * MAX_WORD_SHARE))

    total = sum(natural)
    if total <= available:
        # Give the slack to the last column, so the table spans the page.
        natural[-1] += available - total
        return natural
    if sum(least) >= available:
        return [width * available / sum(least) for width in least]
    spare = available - sum(least)
    extra = [max(0.0, width - low) for width, low in zip(natural, least)]
    return [low + (spare * more / sum(extra) if sum(extra) else 0.0) for low, more in zip(least, extra)]


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

        composer = Composer(path, page_size, footer, reproducible=bool(request.get("reproducible")))
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
