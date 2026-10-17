#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

# The arithmetic of laying a document out on paper, kept apart from the wrapper
# that draws it: this module imports nothing, so the rules it encodes can be
# tested on the host, where reportlab is not installed (it belongs to the
# sandbox the PDF is composed in - see wrapper_render_pdf.py).


def fit_row(row, widths, aligns):
    """Widths and alignments covering every cell of a row.

    A row is normally exactly as wide as the table's columns. One that is wider
    fits its extra cells into the last column, which they share: the row has to
    keep the width of the table, or the cells past the end of it would be drawn
    off the edge of the page - hidden just as surely as if they were dropped.
    """
    if len(row) <= len(widths):
        return widths, aligns
    extra = len(row) - len(widths)
    shared = widths[-1] / (extra + 1)
    return (
        list(widths[:-1]) + [shared] * (extra + 1),
        list(aligns) + ["left"] * extra,
    )


# The characters a word with no spaces in it is broken after, best first: the
# parameters of 'apron;length=25.0', the path of 'imperial-desk-1/side'.
BREAK_AFTER = ";,/=-_:."


def wrap(text, width, measure):
    """'text' broken into lines no wider than 'width', as measured by 'measure'.

    Words go on a line while they fit, as everywhere. A word that does not fit
    on a line of its own - a name with no spaces in it, such as
    'imperial-desk-1/side;apron=25.0,leg=29.28125' - is broken too, rather than
    drawn as wide as it is, over the column beside it or off the edge of the
    page: after the last of 'BREAK_AFTER' that lets the line fit, and between
    any two characters only when nothing else does.

    'measure' is how wide a piece of text is set, in the units of 'width':
    the font's metrics in the wrapper that draws the PDF, a character count in
    a test.
    """
    lines = []
    line = ""
    for word in str(text).split():
        candidate = word if not line else line + " " + word
        if measure(candidate) <= width or not line:
            line = candidate
        else:
            lines.append(line)
            line = word
        while measure(line) > width and len(line) > 1:
            cut = _fitting(line, width, measure)
            lines.append(line[:cut].rstrip())
            line = line[cut:].lstrip()
    lines.append(line)
    return lines


def _fitting(line, width, measure):
    """Where to break a line that does not fit: the most of it that does, at a good place if there is one."""
    fits = 1
    while fits < len(line) and measure(line[: fits + 1]) <= width:
        fits += 1
    for char in BREAK_AFTER:
        best = line.rfind(char, 0, fits)
        # A break that leaves next to nothing on the line is worse than a
        # break at a lesser character, or than one mid-word.
        if best >= fits // 3:
            return best + 1
    return fits
