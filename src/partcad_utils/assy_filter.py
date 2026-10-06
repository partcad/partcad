#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The link mask that selects a part of an assembly, and what reading one means.

A *filter* names the links of an assembly (or of a scene -- the same document
read for another purpose) that are to be kept, as a tree mirroring the tree the
ASSY file already is:

  .. code-block:: yaml

    head:                 # kept, and only the children named under it
      head_half_1:
    bolt:                 # kept, with everything inside it

Three rules, and nothing else:

  * a link the filter names is kept, and a link it does not name is dropped;
  * a link named with nothing under it keeps everything under it;
  * a link named with at least one child under it keeps those children and
    drops its other ones.

That is the whole of the semantics, and it is written down once here because
three things read a filter and all three have to agree: ``pc filter``, which
writes a filtered copy of an ASSY file as a new object of the package;
``pc render``/``pc export``, which filter the assembly they have built rather
than any file; and the IDE's 2D and Draft tabs, which compose one out of the
boxes the user ticked in the panel beside the drawing. A copy of these rules per
caller is a copy that comes to disagree, and a disagreement means a picture that
does not show what the tree said it would.

What a link is called follows one rule, and it is the rule PartCAD itself
addresses a child by -- what a ``connect:`` names, what a ``map:`` names, and
what the IDE shows as the node's label (see ``Assembly.link_name``):

  1. the node's ``name:``, where it gives one;
  2. otherwise the part or the assembly it places;
  3. otherwise its position in the ``links:`` list it is written in, one-based,
     as ``link#2`` (`synthetic_link_name`).

Only a ``links:`` container reaches the third: a node that places something is
named after it. The third exists so that **every** link has a name -- there is
no such thing as a link a filter cannot address, and no second rule for the ones
that used to have none. It is positional rather than invented from the content
so that a reader can count the entries of the file and arrive at the same name.

A filter may also name **any** link by its position, ``link#3``, whatever it is
called otherwise. Names need not be unique - an ASSY file that generates four
legs in a loop may well call every one of them ``leg`` - and a filter that can
only say ``leg`` keeps all four or none. The position is what tells them apart,
so it is accepted for every link and not only for the ones that have no other
name (`Filter.select_link`). The IDE's panel names a link that way exactly when
its label is not unique among its siblings.

This module is pure data: it reads the mask, and it filters an ASSY *document*
(the parsed YAML). Filtering an assembly that has already been built is
``partcad.assembly_filter``, which needs the objects; it lives there and reads
the mask from here. Nothing in this file needs ``partcad``, a CAD kernel, or a
loaded context, which is what lets a client resolve the argument on its own
machine -- where the file the user named actually is -- and send the daemon the
mask rather than a path it cannot open.
"""

import os

import yaml

# The key an ASSY node holds its children under.
LINKS = "links"

# The keys that name what a node places, in the order a node's name falls back
# through them. 'name:' wins over both; see 'link_name()'.
PLACES = ("part", "assembly")

# What a link is called when neither it nor what it places gives it a name: its
# position in the list it is written in, one-based. The '#' is deliberate -- it
# is not a character anybody reaches for in a part name, so a declared name and
# a positional one are told apart on sight and a collision between them is
# vanishingly unlikely (and reported where it happens: see
# 'AssemblyFactoryAssy.handle_node_list').
SYNTHETIC_LINK = "link#%d"


def synthetic_link_name(index: int) -> str:
    """The name the link at ``index`` of a ``links:`` list has, having no other."""
    return SYNTHETIC_LINK % (index + 1)


class FilterError(ValueError):
    """A filter that cannot be read as a mask of link names.

    A ``ValueError`` so that a caller which already turns one into a usage error
    -- every CLI command does -- needs to know nothing about this module.
    """


class Filter:
    """One level of a mask: which links are kept, and what is kept inside them.

    ``children`` is ``None`` for a mask that keeps everything below it, which is
    what a link named with nothing under it means. Otherwise it maps a link name
    to the mask that applies inside that link.
    """

    __slots__ = ("children",)

    def __init__(self, children: dict = None):
        self.children = children

    @property
    def keeps_all(self) -> bool:
        """Whether this mask keeps everything it is applied to, unexamined."""
        return self.children is None

    def select(self, name):
        """The mask for the link called ``name``, or ``None`` if it is dropped.

        A mask that keeps everything answers for every name, which is what makes
        a subtree below a named link cost nothing to walk.
        """
        if self.children is None:
            return self
        if name is None:
            return None
        return self.children.get(name)

    def select_link(self, name, index=None):
        """The mask for one link of a list, and which key selected it: ``(key, mask)``.

        By the link's name, and failing that by its position (``link#N``),
        which any link answers to - see the module docstring. ``(None, None)``
        when neither is named, which means the link is dropped. A mask that
        keeps everything answers ``(name, self)``.
        """
        if self.children is None:
            return name, self
        if name is not None and name in self.children:
            return name, self.children[name]
        if index is not None:
            positional = synthetic_link_name(index)
            if positional in self.children:
                return positional, self.children[positional]
        return None, None

    def names(self) -> list:
        """The link names this level mentions, in the order they were written."""
        return [] if self.children is None else list(self.children)

    def data(self):
        """The mask as the plain data it was read from.

        What it round-trips to: ``None`` for a mask that keeps everything, and
        otherwise a mapping of name to the same. The order the names were
        written in is kept, because a message that lists them should list them
        the way the user did.
        """
        if self.children is None:
            return None
        return {name: mask.data() for name, mask in self.children.items()}

    def key(self) -> str:
        """What makes two masks the same mask, for a cache or a dictionary.

        Canonical: the names sorted, so that two spellings of one selection are
        one key. Used to build the subset an output file is of at most once per
        selection however many file types ask for it (see
        'Shape._output_subject_async').
        """
        if self.children is None:
            return "*"
        return "{%s}" % ",".join("%s:%s" % (name, self.children[name].key()) for name in sorted(self.children))

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Filter(*)" if self.children is None else "Filter(%r)" % (self.children,)


# A mask that keeps everything, for a caller with nothing to filter by.
KEEP_ALL = Filter()


def parse(data, where: str = "the filter") -> Filter:
    """Read one level of a mask out of the data a filter parsed to.

    Accepts the two shapes a tree of names is written in -- a mapping of name to
    sub-mask, and a list of names (whose items may themselves be mappings, which
    is how a list carries a sub-mask) -- plus the three ways of saying "and
    everything under it": nothing at all, an empty collection, and ``true``.

    Anything else is a ``FilterError`` naming where it was found. A filter is the
    one argument of the operation that says what the result contains, so a value
    it cannot read is refused rather than taken for "keep everything" -- which
    would quietly produce the unfiltered object.
    """
    if data is None or data is True:
        return Filter()
    if isinstance(data, dict):
        if not data:
            return Filter()
        children = {}
        for name, value in data.items():
            if name is None or isinstance(name, (dict, list)):
                raise FilterError("%s: a link name is expected, got %r" % (where, name))
            name = str(name)
            children[name] = parse(value, "%s: '%s'" % (where, name))
        return Filter(children)
    if isinstance(data, list):
        if not data:
            return Filter()
        children = {}
        for item in data:
            if isinstance(item, dict):
                inside = parse(item, where)
                if inside.keeps_all:
                    # An empty mapping among the names. On its own '{}' means
                    # "and everything under it", which says nothing about a
                    # *list* of names -- and reading its children would reach
                    # through the 'None' that means it, so this was an
                    # AttributeError rather than the usage error every other
                    # unreadable filter gets.
                    raise FilterError("%s: an empty mapping names no link" % where)
                for name, mask in inside.children.items():
                    children[name] = mask
            elif isinstance(item, str):
                children[item] = Filter()
            else:
                raise FilterError("%s: a link name or a mapping of them is expected, got %r" % (where, item))
        return Filter(children)
    if isinstance(data, str):
        # A bare word is the one shape deliberately refused. It is what an
        # unreadable filter *file* parses to -- 'pc render --filter typo.yaml'
        # with no such file -- and reading it as a link name would turn that
        # typo into a render of nothing, with nothing said about it.
        raise FilterError(
            "%s: a mapping or a list of link names is expected, got the plain text %r. "
            "Write it as '{%s: null}' to name one link" % (where, data, data)
        )
    raise FilterError("%s: a mapping or a list of link names is expected, got %r" % (where, data))


def resolve_spec(spec: str):
    """The data a ``<filter-file|filter-expression>`` argument names.

    A filename first, because that is what a filter normally is: a file somebody
    keeps beside the package and edits. Only when there is no such file is the
    argument read as the filter itself, written out as JSON or YAML -- which is
    the convenient form for one link and for whatever a script composes.

    Resolved by whoever holds the file, which is the client: the daemon may be
    on another machine, where the path names nothing, and the mask is small
    enough to send instead. Returns ``(data, source)``, where ``source`` says
    where it came from for the log.

    Raises:
        FilterError: there is no such file and the text is not a filter either,
            or the file is there and does not parse. Both say which of the two
            happened, because a mistyped filename and a malformed filter are
            fixed in different places.
    """
    if not isinstance(spec, str) or not spec.strip():
        raise FilterError("No filter is given")

    try:
        is_file = os.path.isfile(spec)
    except (OSError, ValueError):
        # A path too long for the platform, or one with a null byte in it: not a
        # file, and the text is what it is going to be read as.
        is_file = False

    if is_file:
        try:
            with open(spec, "r", encoding="utf-8-sig") as f:
                text = f.read()
        except (OSError, UnicodeDecodeError) as e:
            raise FilterError("Failed to read the filter file %s: %s" % (spec, e)) from e
        try:
            # YAML is a superset of JSON, so one parser reads both and a '.json'
            # filter needs no second code path.
            data = yaml.safe_load(text)
        except yaml.YAMLError as e:
            raise FilterError("The filter file %s is not valid JSON or YAML: %s" % (spec, e)) from e
        return data, spec

    try:
        data = yaml.safe_load(spec)
    except yaml.YAMLError as e:
        raise FilterError("There is no filter file '%s', and it is not JSON or YAML either: %s" % (spec, e)) from e
    if not isinstance(data, (dict, list)):
        raise FilterError(
            "There is no filter file '%s', and it is not a JSON or YAML mapping or list of link names either" % spec
        )
    return data, "the command line"


def load(spec: str) -> Filter:
    """The mask a ``<filter-file|filter-expression>`` argument asks for."""
    data, source = resolve_spec(spec)
    return parse(data, "the filter from %s" % source)


def of(data) -> Filter:
    """The mask a request carries, which may already be the mask itself.

    What arrives over the wire is the data a client resolved (see
    ``resolve_spec``); a client that sent the expression as text instead has it
    read here, as an expression and never as a path -- the daemon is not where
    the user's files are. ``None`` is no filter at all.
    """
    if data is None:
        return None
    if isinstance(data, Filter):
        return data
    if isinstance(data, str):
        try:
            parsed = yaml.safe_load(data)
        except yaml.YAMLError as e:
            raise FilterError("The filter is not valid JSON or YAML: %s" % e) from e
        return parse(parsed)
    return parse(data)


# ---- reading an ASSY document ----------------------------------------------


def link_name(node, index=None):
    """What the ASSY file calls this node: the three rules at the top of this file.

    ``index`` is the node's position in the ``links:`` list it belongs to, which
    is what the third rule needs. Without one a node that gives itself no name
    and places nothing answers ``None`` -- which is what a caller that is
    looking at a node out of context (a node that is a whole file, say) has to
    be told rather than given a position it does not have.
    """
    if not isinstance(node, dict):
        return None
    name = node.get("name")
    if name is not None:
        return str(name)
    for key in PLACES:
        value = node.get(key)
        if value is not None:
            return str(value)
    return None if index is None else synthetic_link_name(index)


def colliding_positional_names(links) -> list:
    """The links of one list whose *positional* name another link also answers to.

    ``[(index, name)]``, in file order. One case reaches this: a link that
    writes out ``name: link#2`` beside a second entry that names itself nothing
    and is therefore called ``link#2`` as well. Two links of one name is a
    defect in the file either way -- a ``connect:`` naming it reaches the first
    of them -- and `AssemblyFactoryAssy.link_names` reports it when the file is
    read.

    Filtering is where it stops being recoverable, which is why this is here as
    well as there: the positional name is *written down* as the link is kept
    (see `filter_document`), so the result would hold two links called
    ``link#2`` and nothing afterwards could tell them apart or say which the
    filter had meant.

    Two links that both declare one name, or that are both named after the same
    part, are not this: nothing is written down for them, so a filtered copy is
    no more ambiguous than the file it came from.
    """
    answers = {}
    for index, node in enumerate(links):
        if isinstance(node, dict):
            answers.setdefault(link_name(node, index), []).append(index)
    found = []
    for index, node in enumerate(links):
        if isinstance(node, dict) and link_name(node) is None:
            name = link_name(node, index)
            if len(answers.get(name, ())) > 1:
                found.append((index, name))
    return found


def is_container(node) -> bool:
    """Whether this node holds other nodes rather than placing an object."""
    return isinstance(node, dict) and node.get(LINKS) is not None


def filter_document(document, mask: Filter) -> list:
    """Drop from ``document`` every link ``mask`` does not keep.

    ``document`` is the parsed ASSY file and is filtered **in place**: the lists
    it holds are replaced with the kept items, and every item kept is the very
    object that was there. That is what preserves the comments and the Jinja2
    expressions of a document loaded round-trip -- a rebuilt node would be the
    same data written afresh, and a filtered copy of somebody's file should
    still read like their file.

    Returns what the filter said that the document could not honour, as
    sentences for the caller to report. An empty list means the result is
    exactly what was asked for.
    """
    problems: list = []
    links = document.get(LINKS) if isinstance(document, dict) else None
    if links is not None:
        # Before anything is touched: a name the filter selects that two links
        # answer to cannot be honoured, and keeping both would write the
        # ambiguity into the result. Raised rather than reported, because
        # 'filter_document' mutates as it walks and a half-filtered document is
        # not an answer -- and because every other problem it reports is "more
        # was kept than you asked for", which a reader can still act on.
        _refuse_ambiguous(links, mask, "the filter")
    if links is None:
        # A file that is one part or one assembly and nothing else. There is no
        # list of links to select from, and a filter has nothing to say about
        # it.
        if not mask.keeps_all:
            problems.append(
                "this file places a single object and has no 'links:' to select from, so the filter %s "
                "selects nothing" % _quoted(mask.names())
            )
        return problems
    document[LINKS] = _filter_links(links, mask, "the filter", problems)
    return problems


def _refuse_ambiguous(links, mask: Filter, where: str) -> None:
    """Refuse a selection that two links of one list answer to.

    Walks only the lists the mask reaches: a collision the filter does not name
    is dropped along with both links and writes nothing down, so it is the
    file's business and not this operation's (``pc lint`` and the ASSY reader
    are where it is reported).
    """
    if mask.keeps_all:
        return
    for index, name in colliding_positional_names(links):
        if mask.select(name) is not None:
            raise FilterError(
                "%s: '%s' names two links here -- link %d has no name of its own and is called that by its "
                "position, and another link here is called that outright. Give one of them a 'name' of its own"
                % (where, name, index + 1)
            )
    for index, node in enumerate(links):
        if not isinstance(node, dict) or not is_container(node):
            continue
        _key, sub = mask.select_link(link_name(node, index), index)
        if sub is not None:
            _refuse_ambiguous(node[LINKS], sub, "%s: '%s'" % (where, link_name(node, index)))


def _filter_links(links, mask: Filter, where: str, problems: list) -> list:
    """The items of one ``links:`` list that ``mask`` keeps, in file order.

    One list is one namespace, and every item in it has a name (see the rules at
    the top of this file), so this is a lookup per item and nothing else.
    """
    if mask.keeps_all:
        return list(links)

    kept = []
    used = set()
    for index, node in enumerate(links):
        if not isinstance(node, dict):
            # The schema does not allow it and nothing can be said about it;
            # it is carried through rather than silently dropped.
            kept.append(node)
            continue

        name = link_name(node, index)
        key, sub = mask.select_link(name, index)
        if sub is None:
            continue
        used.add(key)
        if link_name(node) is None:
            # Its name was its position, and filtering moves it: the second link
            # of five is the first of two once the one above it has gone. So the
            # name is written down as the node is kept, which keeps a
            # 'connect:' that named it pointing at it -- and says in the file
            # what it is called, which is worth having in a generated document
            # anyway.
            node["name"] = name
        if sub.keeps_all:
            kept.append(node)
            continue
        if is_container(node):
            node[LINKS] = _filter_links(node[LINKS], sub, "%s: '%s'" % (where, name), problems)
            kept.append(node)
            continue
        # A link that places a part or an assembly of another package: what is
        # inside it is that object's, and this file cannot say which of it to
        # keep. The link is kept whole and the filter is told what it could not
        # do -- 'pc render --filter' does select inside such a link, because it
        # filters the assembly it built rather than this file.
        problems.append(
            "%s: '%s' places %s, so this file cannot select inside it; it is kept whole. "
            "'pc render --filter'/'pc export --filter' do select inside one" % (where, name, _places(node))
        )
        kept.append(node)

    for name in mask.names():
        if name not in used:
            problems.append("%s: there is no link called '%s' here" % (where, name))
    return kept


def _places(node) -> str:
    """What a node places, in words, for a message about it."""
    for key in PLACES:
        value = node.get(key)
        if value is not None:
            return "the %s '%s'" % (key, value)
    return "an object"


def _quoted(names) -> str:
    return ", ".join("'%s'" % name for name in names)
