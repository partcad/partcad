#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Reading a STEP file as the text it is, without a CAD kernel.

A STEP file is ISO 10303-21: a header, and then a list of
'#<id> = ENTITY(<arguments>);' records, in plain text. Two modules here read one
that way rather than putting the question to a sandbox -- 'tolerance_inspect',
for the GD&T a part is toleranced to, and 'step_metadata', for the layers and
the properties a file states about itself and its contents. The core process
holds no live shapes, so either of them going through OCCT would cost a process
per part to answer a question the bytes already answer.

What they share is the lexing, and it is the half that is easy to get subtly
wrong: a record may straddle the block boundary a streaming read cuts at, a
Part 21 string may hold the ';' that would otherwise end a record, and a comment
may hold anything at all. Two copies of that would not fail when they drifted -
they would disagree, one module reading a file the other could not.

Nothing here knows what any entity means. What is above it decides which records
it wants; this decides where a record starts and stops.
"""

import re

# How much of the file is read at a time. The scan is a sequence of byte
# searches over each block, so this trades a little memory for the number of
# them; a STEP file of any size is read in one pass either way.
CHUNK = 1 << 20

# A Part 21 string: single-quoted, with a doubled quote standing for one inside
# it. Spelled without an alternation so that a run of ordinary characters has
# one way to be matched and the engine has nothing to backtrack over.
STRING = re.compile(rb"'[^']*(?:''[^']*)*'")

# An argument that is a reference to another record, and nothing else.
REFERENCE = re.compile(rb"^#(\d+)$")


def scan(path, keywords, read_block):
    """Read the file at 'path' a block of whole records at a time.

    'read_block' is called with each block, which always begins and ends at a
    record boundary, so a caller may look for a record anywhere in it without
    having to think about what was cut off. 'keywords' is what has to appear in
    a block for it to be worth looking at closely: nearly every record in a STEP
    file is a point, a curve or a face, and a block holding none of them is
    dropped whole rather than handed on. That is what keeps reading a 500 MB
    assembly a scan rather than a parse.

    The comments are taken out of a block before it is handed on, because what is
    inside one means nothing and every pattern a caller writes would read it as
    though it did. The strip happens *after* the keyword test, so a file with
    none of them in it costs one scan per block rather than two.
    """
    with open(path, "rb") as f:
        buffer = b""
        while True:
            chunk = f.read(CHUNK)
            if not chunk:
                break
            buffer += chunk
            cut = boundary(buffer)
            if cut <= 0:
                continue
            head, buffer = buffer[:cut], buffer[cut:]
            _hand_on(head, keywords, read_block)
        if buffer:
            _hand_on(buffer, keywords, read_block)


def _hand_on(block, keywords, read_block):
    """One block, to the caller, if there is anything in it for them."""
    if keywords and not any(keyword in block for keyword in keywords):
        return
    read_block(without_comments(block))


def header(path, limit=CHUNK):
    """The bytes of the file's HEADER section, comments and all cut out.

    The header is the first thing in the file and it is short - a description,
    a file name, a schema - so it is read as far as the 'ENDSEC;' that closes
    it and no further. 'limit' is where to give up: a file whose first block
    holds no 'ENDSEC;' is not one with a very long header, it is one that is not
    a STEP file, and reading all of it to find that out would be the expensive
    way round.

    Returned as b"" for a file with no header, which is the same answer as a
    header that says nothing and is the right one for both: what is wanted here
    is what the file states about itself.
    """
    with open(path, "rb") as f:
        buffer = f.read(limit)
    start = buffer.find(b"HEADER")
    if start < 0:
        return b""
    end = buffer.find(b"ENDSEC", start)
    if end < 0:
        return b""
    return without_comments(buffer[start + len(b"HEADER") : end])


def boundary(buffer):
    """How much of 'buffer' is whole records, ending just past the last ';'.

    The file arrives a block at a time and a record straddles the join, so each
    block is cut back to the last record that ended in it and the rest is
    carried forward. The cut has to skip the ';' that a Part 21 string may hold
    -- a tolerance carries a name and a description, both free text -- because
    cutting inside a record would split it into two halves that each parse as
    something else, and quietly lose what it stated.

    'buffer' always begins at a record boundary, which is what lets this start
    outside a string every time it is called.

    Strings are stepped over by hand rather than with 'STRING', because the
    question here is asked of text that may stop in the middle of one. A quote
    at the very end of the buffer is either the end of a string or the first
    half of the doubled quote that stands for one inside it, and there is no way
    to tell until the next block arrives - so this stops rather than guessing,
    and the same bytes are looked at again with more of them to hand.

    Comments are stepped over for the same reason a string is: Part 21 allows
    '/* ... */' wherever a separator is allowed, and the ';' one may hold ends
    nothing. Which of the three comes first is what decides how the next stretch
    is read - a quote inside a comment is not a string, and a '/*' inside a
    string is not a comment.
    """
    cut = 0
    i = 0
    length = len(buffer)
    while i < length:
        quote = buffer.find(b"'", i)
        semicolon = buffer.find(b";", i)
        comment = buffer.find(b"/*", i)
        if semicolon < 0:
            break
        if 0 <= quote < semicolon and (comment < 0 or quote < comment):
            i = end_of_string(buffer, quote)
            if i < 0:
                break
            continue
        if 0 <= comment < semicolon:
            end = buffer.find(b"*/", comment + 2)
            if end < 0:
                # The comment has not closed in what has arrived.
                break
            i = end + 2
            continue
        cut = semicolon + 1
        i = semicolon + 1
    return cut


def without_comments(block):
    """'block' with its Part 21 comments taken out.

    What is inside one means nothing, and every regular expression above would
    read it as though it did: a comment may hold a semicolon, or text shaped
    like an entity. Removing them once is cheaper than teaching each pattern to
    ignore them, and the common case costs a single scan - a block with no '/*'
    in it is handed straight back.

    A '/*' inside a quoted string opens nothing, which is why this walks the
    strings rather than looking only for the delimiters.
    """
    if block.find(b"/*") < 0:
        return block

    kept = []
    start = 0
    i = 0
    length = len(block)
    while i < length:
        quote = block.find(b"'", i)
        comment = block.find(b"/*", i)
        if comment < 0:
            break
        if 0 <= quote < comment:
            end = end_of_string(block, quote)
            if end < 0:
                break
            i = end
            continue
        kept.append(block[start:comment])
        end = block.find(b"*/", comment + 2)
        if end < 0:
            # Unterminated, so the rest of the block is inside it.
            start = length
            break
        start = end + 2
        i = start
    kept.append(block[start:])
    return b"".join(kept)


def end_of_string(buffer, start):
    """Where the Part 21 string opening at 'start' ends, or -1 if it is cut off."""
    i = start + 1
    length = len(buffer)
    while True:
        quote = buffer.find(b"'", i)
        if quote < 0 or quote + 1 >= length:
            # Unterminated, or terminated by the last byte there is - which may
            # yet turn out to be the first of a doubled quote.
            return -1
        if buffer[quote + 1 : quote + 2] == b"'":
            i = quote + 2
            continue
        return quote + 1


def arguments(block, start):
    """The top-level arguments of the parameter list that opens at 'block[start]'.

    None if it does not close. Reached only for the handful of records a caller
    is interested in, so this walks the bytes rather than looking for a pattern
    in them: a nested list and a string may both hold a comma, and a regular
    expression that got that right would be harder to read than the loop.
    """
    result = []
    depth = 0
    begin = start + 1
    i = start
    length = len(block)
    while i < length:
        char = block[i : i + 1]
        if char == b"'":
            match = STRING.match(block, i)
            if match is None:
                return None
            i = match.end()
            continue
        if char == b"(":
            depth += 1
        elif char == b")":
            depth -= 1
            if depth == 0:
                result.append(block[begin:i].strip())
                return result
        elif char == b"," and depth == 1:
            result.append(block[begin:i].strip())
            begin = i + 1
        i += 1
    return None


def is_text_or_omitted(argument):
    """Whether an argument is a Part 21 string, or the '$' that stands for none.

    An optional string attribute may be written either way, so a reader
    insisting on the quote would reject a valid record and lose what it stated -
    silently, which is the worst way to lose one.
    """
    return argument == b"$" or argument.startswith(b"'")


def text(argument):
    """A Part 21 string argument as a str, or None if it is not one.

    The quotes come off and a doubled quote becomes the one it stands for. '$'
    -- the omitted value -- is None rather than the empty string: a file that
    left a description out and one that wrote an empty description are saying
    different things, and only the second of them is saying anything.

    Part 21's own escapes for characters outside the base alphabet ('\\X2\\...'
    and friends) are left as they stand. They are rare, they are meaningful only
    to a reader that decodes them, and half-decoding text is worse than handing
    it over as written.
    """
    if argument is None or argument == b"$":
        return None
    if not argument.startswith(b"'") or not argument.endswith(b"'") or len(argument) < 2:
        return None
    return argument[1:-1].replace(b"''", b"'").decode("utf-8", errors="replace")


def references(argument):
    """The record ids in a '(#1,#2,#3)' list argument, as ints.

    An empty list for anything that is not one, including the '$' that stands
    for an omitted list: what a caller does with this is count or follow the
    entries, and both of those are right to do nothing with none.
    """
    if not argument:
        return []
    return [int(id) for id in re.findall(rb"#(\d+)", argument)]


def reference(argument):
    """The record id an argument refers to, or None if it is not a reference."""
    if argument is None:
        return None
    match = REFERENCE.match(argument)
    return None if match is None else int(match.group(1))


def number(argument):
    """An argument read as a float, or None if it is not written as one."""
    if argument is None:
        return None
    try:
        return float(argument)
    except (TypeError, ValueError):
        return None
