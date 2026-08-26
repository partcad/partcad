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
