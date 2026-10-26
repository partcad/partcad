#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#

"""Assembly documents: what a generated document says about an assembly.

Three documents are generated from an assembly, and this module is what they
have in common. The markdown one ('pc render -t readme') lists what the assembly
is made of; the PDF ('-t pdf') and the HTML ('-t html') are an assembly
instruction book - the same bill of materials, plus a page for every step of
putting the thing together. All three are built here as the format-independent
model in 'document.py', so they cannot drift apart, and each output format is
just a way of writing that model down.

The instruction book is only defined for an assembly that PartCAD knows how to
assemble, which today means an Assembly YAML (ASSY) file: that is where the
order of the steps and the joints between the items come from. Anything else -
an assembly imported as a single file, an alias to something that is not an
ASSY - has no steps to describe, and is refused rather than silently reduced to
a title page and a parts list.
"""

import asyncio
import copy
import math
import os
import re
import tempfile
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Optional

from . import assembly_explode
from . import document as doc
from . import logging as pc_logging
from .assembly import Assembly
from .exception import NotAnAssemblyFileError, NotManufacturableError
from .geom import Location
from .render import render_cfg_merge
from .sandbox_lock import process_slots

# How far apart an exploded view pulls the two items of a step, and what that
# falls back to. The rules are 'assembly_explode''s, which an assembly declared
# with 'exploded: true' is drawn by too, so that the two cannot disagree.
EXPLODED_FRACTION = assembly_explode.EXPLODED_FRACTION
FALLBACK_EXPLODED_DISTANCE = assembly_explode.FALLBACK_EXPLODED_DISTANCE

# How far a fastener is pulled out of its hole in the picture of driving it in,
# as a fraction of its own length: a little more than all of it, so that its
# point is clear of what it goes through.
FASTENER_PULL = 1.25

# The two colours a step is drawn in: what is there already, and what the step
# adds. A light grey that recedes on white paper, and a blue that stands out
# against it and against the red the gap is drawn in.
CONTEXT_COLOR = "#A8A8A8"
NEW_COLOR = "#1565C0"

# An item is shown on its own, in the box of parts of its step, when it is
# smaller than this fraction of the finished assembly: something that size is
# hard to pick out in a picture of the whole - a screw, a bracket - while a
# board or a panel is the thing the picture is of.
SMALL_FRACTION = 0.25

# How many parts a package has to contribute before the guide links to it. The
# document is for whoever is assembling the thing, and a package that supplies a
# single screw is not where they will go looking for anything.
SUPPLIER_LINK_THRESHOLD = 3

# How many times an alias is followed before giving up on a cycle.
MAX_ALIAS_DEPTH = 16

# The formats an assembly instruction book is generated in.
GUIDE_FORMATS = ("pdf", "html")


def _sandbox_budget() -> asyncio.Semaphore:
    """How much of one document may be drawn at once.

    A document is built out of work that has nothing to say to itself: every
    step of every assembly asks a sandbox how big its two items are, and every
    page of the book is a projection or three of them. None of it waits on any
    of the rest, and all of it used to be done one item at a time.

    What it costs is a sandbox interpreter -- several hundred megabytes of CAD
    kernel, not a thread -- so the ceiling is the machine's budget for those
    processes, 'partcad.sandbox_lock.process_slots'. Enough of the document in
    flight to keep that budget full is all the concurrency there is any use
    for; more only piles up tasks polling for the same slots. This is the bound
    a recursive render and a recursive route already take, for the same reason.

    A new semaphore per document rather than one for the module: an
    'asyncio.Semaphore' belongs to the loop it first blocks on, and PartCAD
    runs an 'asyncio.run()' per worker thread and one per JSON-RPC request --
    see 'partcad.concurrency' for what a shared one costs there.
    """
    return asyncio.Semaphore(max(1, process_slots.count))


async def _gather_bounded(budget, coroutines) -> list:
    """Await all of them, with at most 'budget' of them under way at once.

    Results come back in the order the coroutines were given, whatever order
    they finished in: a book is read in the order it was written.

    The budget is held around one coroutine and released before the next is
    admitted, so nothing that holds it may wait for something that needs it.
    That is why it is spent here, on the leaves -- measuring a step, drawing an
    illustration -- and never around the page or the section that asked for
    them.
    """

    async def bounded(coroutine):
        async with budget:
            return await coroutine

    return list(await asyncio.gather(*[bounded(coroutine) for coroutine in coroutines]))


def resolve_alias(ctx, assembly):
    """The assembly an alias ultimately points at, or the assembly itself."""
    for _ in range(MAX_ALIAS_DEPTH):
        if assembly is None or assembly.config.get("type") != "alias":
            return assembly
        source = assembly.config.get("source_resolved")
        if source is None or ctx is None:
            return assembly
        resolved = ctx._get_assembly(source)
        if resolved is None or resolved is assembly:
            return assembly
        assembly = resolved
    return assembly


def check_source(assembly, ignore_manufacturability: bool = False):
    """Refuse to write an instruction book for something that has no steps.

    Raises 'NotAnAssemblyFileError' unless the assembly is an ASSY, and
    'NotManufacturableError' unless it is meant to be built at all - the latter
    only when the caller has not asked for that to be ignored.
    """
    kind = assembly.config.get("type")
    if kind != "assy":
        raise NotAnAssemblyFileError(
            "%s:%s is a '%s' assembly, not an Assembly YAML (ASSY) file: there are no assembly steps to document"
            % (assembly.project_name, assembly.name, kind or "unknown")
        )

    if not ignore_manufacturability and not assembly.is_manufacturable:
        raise NotManufacturableError(
            "%s:%s is not manufacturable: pass --ignore-manufacturability to generate the document anyway"
            % (assembly.project_name, assembly.name)
        )


#
# The pictures a document is made of
#


# Which direction an illustration of the book is looked at from, as the
# 'viewport_origin' it is drawn with: the iso views from above first - the view
# a picture of an object is expected to be - and then a view of each side from a
# little above it. An exploded step is drawn from whichever shows its gap best
# (see 'view_along'); everything else from the first.
#
# They are directions and only directions - the renderer looks along them
# whatever it draws and wherever that sits ('LOOK_AT' in
# 'builtin/render/render_svg.py') - so the direction '_gap_visibility' judges is
# the one the picture is drawn from.
ISO_VIEWS = ((100, -100, 100), (100, 100, 100), (-100, 100, 100), (-100, -100, 100))
SIDE_VIEWS = ((0, -100, 50), (100, 0, 50), (0, 100, 50), (-100, 0, 50))

# How much better a side view has to show a gap before it is taken over an iso
# view, which reads as 3D where a side view does not: a push straight down is
# seen nearly as well from an iso corner, a push sideways is not.
SIDE_VIEW_MARGIN = 0.15

VIEW_UP = (0, 0, 1)


def _gap_visibility(view, along) -> float:
    """How much of a gap along 'along' is seen from 'view': 1 across it, 0 end on."""
    v = _normalized(view)
    a = _normalized(along)
    cross = (v[1] * a[2] - v[2] * a[1], v[2] * a[0] - v[0] * a[2], v[0] * a[1] - v[1] * a[0])
    return math.sqrt(sum(c * c for c in cross))


def view_along(along=None):
    """The direction an illustration is drawn from, as a 'viewport_origin'.

    Chosen here rather than read from the package: a package's 'render:' says
    how *its* drawings look - a 'viewport_origin' that suits its catalogue
    pictures, a 'with_ports:' for its connection drawings - and an instruction
    book that inherited it showed a step from wherever that happened to point.
    So the book draws with PartCAD's own options (see 'Shape._output_getopts')
    and picks the view itself: the iso view for an object, and for a step the
    view that shows the gap it opens, 'along' being the way the item moves.
    """
    if not along or _normalized(along) is None:
        return ISO_VIEWS[0]
    iso = max(ISO_VIEWS, key=lambda view: _gap_visibility(view, along))
    side = max(SIDE_VIEWS, key=lambda view: _gap_visibility(view, along))
    if _gap_visibility(side, along) > _gap_visibility(iso, along) + SIDE_VIEW_MARGIN:
        return side
    return iso


def view_facing(directions):
    """The iso view that looks at the most of 'directions' from the side they point to.

    What a step pulls out is seen best from the side it comes out of: a screw
    pulled out of the far face of a leg is behind the leg from anywhere else.
    So the view is the one most of the directions point towards - and, between
    views that do equally well, the first of 'ISO_VIEWS', so that a book whose
    steps all go one way is drawn from one place throughout. Directions are
    what the gaps of the pictures are along; with none, the first view.
    """
    units = [unit for unit in (_normalized(direction) for direction in directions or []) if unit is not None]

    def facing(view):
        v = _normalized(view)
        return sum(max(0.0, sum(v[i] * unit[i] for i in range(3))) for unit in units)

    best = ISO_VIEWS[0]
    for view in ISO_VIEWS[1:]:
        if facing(view) > facing(best) + 1e-9:
            best = view
    return best


class ImageSource:
    """Where the pictures of a document come from."""

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None, along=None, view=None):
        return None

    def shape_image(self, shape, key=None, alt=None, caption=None, annotations=None, along=None, view=None):
        # Inherited by every image source, so each of them offers both forms.
        return asyncio.run(self.shape_image_async(shape, key, alt, caption, annotations, along, view))


class PackageImages(ImageSource):
    """The projections the package has already rendered next to its documents.

    Used by the markdown document, which sits in the package tree and links to
    the images that are in it rather than carrying any of its own.
    """

    def __init__(self, project, render_cfg, output_dir, return_path):
        self.project = project
        self.render_cfg = render_cfg or {}
        self.output_dir = output_dir
        self.return_path = return_path

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None, along=None, view=None):
        # The image is looked up where the shape's own configuration puts it, the
        # same way rendering it there does. Deep copy: the merge is in place.
        image_cfg = render_cfg_merge(copy.deepcopy(self.render_cfg), shape.config.get("render") or {})
        src, test_path = self.project.readme_image_path(shape.name, image_cfg, self.return_path, shape.config)
        if src is None:
            return None
        path = os.path.join(self.output_dir, test_path)
        if not os.path.exists(path):
            # Not a warning: a document of an assembly is routinely asked for
            # without asking for the projections it would illustrate it with,
            # and it is perfectly readable without them.
            pc_logging.debug("No image found for %s at %s" % (shape.name, test_path))
            return None
        return doc.Image(file=path, src=src, alt=alt or shape.name, caption=caption)


class RenderedImages(ImageSource):
    """Projections rendered on the spot, into a directory of their own.

    An instruction book illustrates things that exist nowhere but in it - a pair
    of items pulled apart to show how they meet - so it cannot be assembled out
    of the pictures a package happens to have rendered.

    The pages of a document are composed at the same time, so this is asked for
    several illustrations at once. Two things follow from that, and neither was
    needed while one page was drawn after another.
    """

    def __init__(self, ctx, project, directory, reproducible=False):
        self.ctx = ctx
        self.project = project
        self.directory = directory
        # Whether these projections have to be the same on any machine. A book
        # that is checked in is made of them, so a picture that drifts is a
        # document that drifts -- which is what 'reproducible' on the PDF file
        # type could not settle on its own: it fixes reportlab's clock and
        # leaves the pages it draws alone. See 'Shape.render_svg_somewhere_async'.
        self.reproducible = bool(reproducible)
        self.rendered = {}
        # One lock per illustration, not one over all of them: two pages showing
        # different things have nothing to wait for from each other. What it
        # rules out is two pages showing the *same* thing - the top assembly is
        # on the title page and on its own, and an item is the counterpart of
        # the step after the one that placed it - each finding nothing rendered
        # and both starting a projection into the one file it is named by.
        self._locks = {}
        # And the machine's budget, spent around the projection itself rather
        # than around the page that wanted it, so that a page waiting for a slot
        # is never holding one. See '_sandbox_budget()'.
        self._budget = _sandbox_budget()

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None, along=None, view=None):
        if key is None:
            key = "%s:%s" % (shape.project_name, shape.name)

        lock = self._locks.get(key)
        if lock is None:
            # Nothing is awaited between the lookup and the store, so two tasks
            # of one loop cannot each install a lock of their own here.
            lock = self._locks[key] = asyncio.Lock()

        async with lock:
            path = self.rendered.get(key)
            if path is None:
                path = os.path.join(self.directory, _slug(key) + ".svg")
                os.makedirs(self.directory, exist_ok=True)
                async with self._budget:
                    await shape.render_svg_somewhere_async(
                        ctx=self.ctx,
                        project=self.project,
                        filepath=path,
                        annotations=annotations,
                        # True or nothing: an explicit 'False' is this caller
                        # insisting, and would turn the flag off for a package
                        # that had asked for it on its 'svg:' file type.
                        reproducible=True if self.reproducible else None,
                        viewport_origin=view or view_along(along),
                        viewport_up=VIEW_UP,
                        defaults_only=True,
                    )
                if not os.path.exists(path):
                    pc_logging.warning("Failed to render the illustration of %s" % key)
                    return None
                self.rendered[key] = path

        return doc.Image(file=path, alt=alt or key, caption=caption)


def _slug(text):
    """A file name that stands for an object name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "image"


def _prose(text) -> list:
    """Free-form text from an ASSY file, as the paragraphs of a document.

    A 'description' or a 'comment' is written by hand in YAML, most often as a
    block scalar hard-wrapped to fit the file it is in. Those line breaks belong
    to the file rather than to the text, and the three output formats disagree
    about them - HTML turns one into a '<br/>' and the PDF starts a new line,
    while markdown folds it away - so they are folded here, once, and only a
    blank line, which is the break that was meant, starts a new paragraph.
    """
    if not text:
        return []
    paragraphs = []
    for chunk in re.split(r"\n\s*\n", str(text).strip()):
        collapsed = " ".join(chunk.split())
        if collapsed:
            paragraphs.append(collapsed)
    return paragraphs


def _prose_blocks(text) -> list:
    """The paragraphs of '_prose()', as blocks of a document."""
    return [doc.Paragraph(paragraph) for paragraph in _prose(text)]


#
# The steps of an assembly
#


@dataclass
class GuideFastener:
    """One fastener a step drives in once its item is in place.

    A screw, a nail, a pin: a link whose joint is made by going into the
    material ('selfScrew' or 'snapIn', see 'ConnectHow') and that holds the
    item of the step it follows - it is connected to that item, or driven
    through it on its way into another ('interferes'). Such a link is not a
    step of its own: a person fastens the part they have just positioned, and
    the book says so on the same page (see '_fastens').
    """

    item: object
    item_name: str
    location: Location
    connection: Optional[dict] = None
    description: Optional[str] = None
    comment: Optional[str] = None
    how: object = None
    # Where it is pulled out to in the picture of fastening it, and the line it
    # goes in along.
    direction: tuple = (0.0, 0.0, 1.0)
    distance: float = FALLBACK_EXPLODED_DISTANCE
    gap: Optional[tuple] = None

    @property
    def target(self) -> Optional[str]:
        return (self.connection or {}).get("target")

    @property
    def through(self) -> list:
        """The links it is driven through on its way into its target."""
        return list((self.connection or {}).get("interferes") or [])

    def exploded_location(self) -> Location:
        offset = [self.direction[i] * self.distance for i in range(3)]
        return Location([offset, [0, 0, 1], 0]) * self.location


@dataclass
class GuideStep:
    """One item joined to what is there already, and what fastens it."""

    number: int
    item: object
    item_name: str
    location: Location
    counterpart: object
    counterpart_name: str
    counterpart_location: Location
    connection: Optional[dict] = None
    # Whether the counterpart is the partial assembly of everything placed so
    # far, which exists for this step alone, rather than one of the items.
    counterpart_so_far: bool = False
    # What the ASSY file says about this step in words, as opposed to the
    # sentence 'description()' composes out of the connection: the node's own
    # 'description' (what the item being added is) and the 'comment' of the
    # 'connect'/'connectPorts' section that placed it (context that is
    # deliberately not an instruction - see docs/source/assy.rst).
    item_description: Optional[str] = None
    comment: Optional[str] = None
    # Where the two are pulled apart to, and the line that shows the gap.
    direction: tuple = (0.0, 0.0, 1.0)
    distance: float = FALLBACK_EXPLODED_DISTANCE
    gap: Optional[tuple] = None
    # Everything of this assembly placed before this step, as the children that
    # placed it: what the person following the book has in front of them, and
    # what the pictures of the step show the item going onto.
    context: list = field(default_factory=list)
    # The fasteners driven in once the item is in place ('GuideFastener').
    fasteners: list = field(default_factory=list)
    # The further joints the item makes once placed: the records of its
    # 'alsoConnectPorts' (see 'AssemblyFactoryAssy.resolve_also').
    also: list = field(default_factory=list)
    # How it is put in place, as the 'how' of the connection ('ConnectHow').
    how: object = None

    def exploded_location(self) -> Location:
        """Where the item sits in the exploded view of this step."""
        offset = [self.direction[i] * self.distance for i in range(3)]
        return Location([offset, [0, 0, 1], 0]) * self.location

    def description(self) -> str:
        """What this step does, in words."""
        connection = self.connection or {}
        if connection.get("with_port") and connection.get("to_port"):
            return "Connect the %s port of %s to the %s port of %s." % (
                connection["with_port"],
                self.item_name,
                connection["to_port"],
                self.counterpart_name,
            )
        if connection.get("to_port"):
            return "Connect %s to the %s port of %s." % (
                self.item_name,
                connection["to_port"],
                self.counterpart_name,
            )
        return "Add %s to %s." % (self.item_name, self.counterpart_name)

    def joint_detail(self) -> Optional[str]:
        """Which ports of what meet, and how it goes on, as one short line.

        The step's own words are the node's 'description', written for whoever
        builds it. This is the model's account of the same joint - the names a
        package gave its ports - kept for the reader who checks the book
        against the model, and set apart from the instructions so that the two
        are never mistaken for each other.
        """
        connection = self.connection or {}
        if not connection.get("with_port") or not connection.get("to_port"):
            return None
        text = "%s %s to %s %s" % (
            self.item_name,
            connection["with_port"],
            self.counterpart_name,
            connection["to_port"],
        )
        how = _how_words(self.how)
        return "Joint: %s%s." % (text, ", " + how if how else "")

    def also_sentences(self) -> list:
        """One sentence for every further joint the item makes."""
        return ["It also meets %s." % record.get("name") for record in self.also if record.get("name")]

    def also_detail(self) -> list:
        return [
            "Also: %s %s to %s %s." % (self.item_name, record.get("with"), record.get("name"), record.get("to"))
            for record in self.also
            if record.get("name")
        ]


def _how_words(how) -> Optional[str]:
    """What a connection's 'how' says about putting the item in place, in words."""
    if how is None:
        return None
    if getattr(how, "self_screw", False):
        return "driven in, cutting its own thread"
    if getattr(how, "snap_in", False):
        return "pushed in until it snaps"
    torque = getattr(how, "turn_torque_max", 0) or 0
    if torque > 0:
        return "turned in, up to %g N*m" % torque
    if "pushForceMax" in getattr(how, "_stated", ()):
        return "pushed into place, up to %g N" % how.push_force_max
    return None


@dataclass
class GuideSection:
    """One assembly and the steps it is put together in."""

    assembly: Assembly
    name: str
    steps: list = field(default_factory=list)
    top: bool = False
    # The assembly whose children the steps place: the one above, or what it
    # wraps (see '_step_source'). What a step's pictures are keyed on, with the
    # step's number (see 'exploded_assembly').
    content: Optional[Assembly] = None
    # The item everything else is added to. No step places it - there is nothing
    # yet to place it against - so it is named on the assembly's own page, and
    # it is the only item whose 'description' has nowhere else to go.
    base_name: Optional[str] = None
    base_description: Optional[str] = None
    # How many of this assembly the whole build needs. An assembly used more
    # than once is documented once, so this is what says it has to be made
    # again - and it counts the copies of whatever uses it too, since four
    # towers with a spire each need four spires. The build plan counted it
    # ('build_plan'), the same walk that decided where it is documented.
    count: int = 1
    # Which step each link of the assembly is put in by, by the link's position:
    # 0 for the base, which no step places, and the step a fastener is driven in
    # at for each fastener (see '_fastens'). The build plan lists every link;
    # this is what puts the ones that share a step on that step's page.
    step_of_link: dict = field(default_factory=dict)
    # Everything the assembly is put together from, as the children that place
    # it: what its own page lists as what is needed.
    children: list = field(default_factory=list)
    # The largest dimension of the finished assembly, against which an item
    # counts as small enough to be shown on its own (see '_is_small').
    size: Optional[float] = None
    # What the section was measured with, for what its pages measure in turn.
    ctx: object = None
    # Where every step of the section is drawn from: one place, so that one
    # picture follows on from the one before it (see 'view_facing').
    view: Optional[tuple] = None


def _step_source(assembly):
    """The assembly whose children are the items that get assembled.

    An assembly that holds nothing but one embedded 'links:' container holds
    everything inside that - a file that wrapped its contents in a nested list
    rather than listing them. Such a wrapper is neither a step nor a sub-assembly
    of its own - it is the same thing under another name - so it is looked
    through rather than documented.

    It used to be every assembly's shape: the root node of an ASSY file became a
    container of its own, so a package's assembly held exactly one embedded
    assembly. It is the assembly itself now (see 'AssemblyFactoryAssy'), and this
    is left for the files that nest anyway.
    """
    while len(assembly.children) == 1:
        child = assembly.children[0]
        if not isinstance(child.item, Assembly) or not child.item.config.get("child", False):
            break
        if child.connection is not None:
            break
        assembly = child.item
    return assembly


def _display_name(assembly):
    """What to call an assembly in the document.

    An assembly embedded in an ASSY file is named after the file it is embedded
    in ("logo_embedded:logo_embedded_head"), which is how it is told apart from
    the assemblies of other files, but not how anyone refers to it.
    """
    name = assembly.name or assembly.project_name or ""
    return name.rsplit(":", 1)[-1] or name


def _label(name) -> str:
    """An object's name without the parameter values it was instantiated with.

    'imperial-desk-1/side;apron=25.0,leg=29.28125' is how PartCAD tells two
    instances of one object apart, and is what the bill of materials lists;
    as the title of a page it is a line of text no page is wide enough for and
    no reader needs. The values are on the page, beside it ('_parameters').
    """
    return str(name or "").split(";", 1)[0]


def _parameters(name) -> Optional[str]:
    """The parameter values a name carries, written to be read: 'apron 25, leg 29.28125'."""
    _, _, values = str(name or "").partition(";")
    if not values:
        return None
    return ", ".join(
        "%s %s" % (key, _number_words(value)) for key, _, value in (pair.partition("=") for pair in values.split(","))
    )


def _number_words(value) -> str:
    """A number the way it reads: '25.0' is 25, '29.28125' stays as it is."""
    try:
        number = float(value)
    except (TypeError, ValueError):
        return str(value)
    return ("%.6f" % number).rstrip("0").rstrip(".")


def _assembly_key(assembly):
    """What makes two assemblies the same one for the purpose of documenting it.

    An assembly a package declares is the very same object wherever it is used,
    so its name identifies it. An assembly embedded in the 'links:' of an ASSY
    file belongs to no package and is a fresh object at each place it appears,
    so nothing but its identity can tell two of them apart.
    """
    if assembly.config.get("child", False):
        return id(assembly)
    return (assembly.project_name, assembly.name)


async def _build_section(ctx, assembly, content=None, top=False, budget=None):
    """The section documenting one assembly, steps measured.

    Composing the steps is bookkeeping over what the ASSY file already says, and
    it stays in order: each step is joined to what the steps before it have
    placed. A fastener that holds the item a step has just positioned is driven
    in at that same step rather than at one of its own (see '_fastens'), so a
    step is a part and the screws that hold it. Measuring them is not
    bookkeeping - it is a sandbox process per item - and one step's
    measurements tell the next step nothing, so they are all taken at once.

    'budget' is the caller's, when several sections are being built together, so
    that the sections share one ceiling rather than take one each.
    """
    if content is None:
        content = _step_source(assembly)
    section = GuideSection(assembly=assembly, name=_display_name(assembly), top=top, ctx=ctx, content=content)
    section.children = list(content.children)

    placed = []
    for position, child in enumerate(content.children):
        if not placed:
            # The first item is what everything else is added to; there is
            # nothing yet to connect it to.
            section.base_name = child.name or child.item.name
            section.base_description = child.description
            section.step_of_link[position] = 0
            placed.append(child)
            continue

        if section.steps and _fastens(child, section.steps[-1]):
            section.steps[-1].fasteners.append(
                GuideFastener(
                    item=child.item,
                    item_name=child.name or child.item.name,
                    location=child.location or Location(),
                    connection=child.connection,
                    description=child.description,
                    comment=child.comment,
                    how=child.how,
                )
            )
            section.step_of_link[position] = section.steps[-1].number
            placed.append(child)
            continue

        counterpart, counterpart_name, counterpart_location = _counterpart(content, placed, child)
        step = GuideStep(
            number=len(section.steps) + 1,
            item=child.item,
            item_name=child.name or child.item.name,
            location=child.location or Location(),
            counterpart=counterpart,
            counterpart_name=counterpart_name,
            counterpart_location=counterpart_location,
            counterpart_so_far=all(counterpart is not candidate.item for candidate in placed),
            connection=child.connection,
            item_description=child.description,
            comment=child.comment,
            context=list(placed),
            also=list(getattr(child, "also", None) or []),
            how=child.how,
        )
        section.steps.append(step)
        section.step_of_link[position] = step.number
        placed.append(child)

    budget = budget if budget is not None else _sandbox_budget()
    await _gather_bounded(budget, [_resolve_step_geometry(ctx, step) for step in section.steps])
    section.view = view_facing(
        [step.direction for step in section.steps]
        + [fastener.direction for step in section.steps for fastener in step.fasteners]
    )
    if ctx is not None:
        try:
            section.size = await assembly.get_max_dimension_async(ctx)
        except Exception as e:  # pylint: disable=broad-except
            # A size is what decides which items get a picture of their own;
            # without one every item does, which is a longer page and nothing
            # worse.
            pc_logging.debug("Could not measure %s: %s" % (assembly.name, e))

    return section


def _fastens(child, step) -> bool:
    """Whether a link is a fastener for the item a step has just positioned.

    A fastener is what makes its joint by going into the material - a screw
    cutting its own thread, a pin or a clip snapped in - which is what its
    'how' says, or the mating or the interfaces it connects through ('selfScrew',
    'snapIn'). It fastens the item of the step before it when it is connected
    to that item or driven through it into something else ('interferes'), and
    then a person drives it in as part of that step: the part is positioned,
    and then screwed down. A run of the same fastener after another fastener
    belongs to the same step too, so that a step adding a screw with nothing to
    fasten it to adds as many of them as follow it, at once.

    Anything else - including a fastener that holds something placed steps ago
    - is a step of its own.
    """
    how = getattr(child, "how", None)
    if how is None or not (getattr(how, "self_screw", False) or getattr(how, "snap_in", False)):
        return False
    connection = child.connection or {}
    target = connection.get("target")
    through = connection.get("interferes") or []
    if target == step.item_name or step.item_name in through:
        return True
    return _object_key(child.item) == _object_key(step.item)


def _object_key(item) -> str:
    """What makes two items the same thing to fetch: the same object, with the same parameters."""
    return "%s:%s" % (getattr(item, "project_name", ""), getattr(item, "name", ""))


def _counterpart(assembly, placed, child):
    """What the item of this step is joined to (see 'assembly_explode.counterpart')."""
    return assembly_explode.counterpart(assembly, placed, child)


async def _resolve_step_geometry(ctx, step: GuideStep):
    """How far apart to pull the two items of a step, and which way.

    'assembly_explode.separation_async', which is also how far an item of an
    assembly declared 'exploded: true' backs out of what it is joined to.

    Each fastener of the step backs out of what it is driven into: along the
    normal of the port it was connected to, away from that item - which is the
    way its head is - by a little more than its own length, so that its point
    clears whatever it goes through.
    """
    separation = await assembly_explode.separation_async(
        ctx, step.item, step.location, step.counterpart, step.counterpart_location, step.connection
    )
    step.direction = separation.direction
    step.distance = separation.distance
    step.gap = separation.gap

    await asyncio.gather(*[_resolve_fastener_geometry(ctx, step, fastener) for fastener in step.fasteners])


async def _resolve_fastener_geometry(ctx, step: GuideStep, fastener: GuideFastener):
    """Which way a fastener of a step is pulled out to show it, and how far."""
    target_item, target_location = step.item, step.location
    for child in step.context:
        if child.name == fastener.target and child.name != step.item_name:
            target_item, target_location = child.item, child.location or Location()
            break
    center, target_center, length = await asyncio.gather(
        _placed_center(ctx, fastener.item, fastener.location),
        _placed_center(ctx, target_item, target_location),
        fastener.item.get_max_dimension_async(ctx),
    )
    away = [center[i] - target_center[i] for i in range(3)]
    direction = _normalized((fastener.connection or {}).get("direction")) or _normalized(away) or (0.0, 0.0, 1.0)
    if sum(direction[i] * away[i] for i in range(3)) < 0:
        direction = tuple(-value for value in direction)
    fastener.direction = direction
    exploded = (fastener.connection or {}).get("exploded")
    if exploded is not None:
        fastener.distance = float(exploded)
    else:
        fastener.distance = FASTENER_PULL * length if length else FALLBACK_EXPLODED_DISTANCE
    # Along the line it goes in by: from where it ends up to where it is shown.
    end = [center[i] + direction[i] * fastener.distance for i in range(3)]
    fastener.gap = (list(center), end)


# The two 'view_along' reads, under the names this module has always had.
_placed_center = assembly_explode.placed_center
_normalized = assembly_explode.normalized


def _group(project_name, name, color, children):
    """Some items, where they are, drawn in one colour: one layer of a step's picture.

    'children' are '(item, name, location)'. The colour is the group's, and an
    item inherits it unless it states one of its own (see
    'builtin/render/appearance' in the wrappers): which is how a picture tells
    what is there already from what is being added, in a drawing that has
    nothing else to tell them apart by.
    """
    group = Assembly(
        project_name,
        {"name": name, "child": True, "cache": False, "properties": {"color": color}},
    )
    group.instantiate = lambda _: True
    for item, item_name, location in children:
        group.add(item, item_name, location)
    return group


def _picture(project_name, name, layers):
    """An assembly of nothing but the layers of one picture, each at the origin."""
    picture = Assembly(project_name, {"name": name, "child": True, "cache": False})
    picture.instantiate = lambda _: True
    for layer_name, layer in layers:
        if layer.children:
            picture.add(layer, layer_name, Location())
    return picture


def exploded_assembly(section: GuideSection, step: GuideStep) -> Assembly:
    """What a step adds, pulled off what is there already: the picture of positioning it.

    Everything placed before the step is drawn where it is, in CONTEXT_COLOR -
    the assembly so far, which is what the reader has in front of them - and the
    item of the step in NEW_COLOR, held off the joint along which it goes on.
    A step with nothing placed before it in its own assembly - there is none:
    the base is placed by no step - would show the counterpart alone.

    Named after the assembly the step belongs to as well as the step's number:
    the sections of a book are drawn at once, so every section's first step is
    being projected at the same time, and an action is told apart from the
    others open beside it by the name of what it is working on (see
    'logging_ansi_terminal.action_key').
    """
    project_name = getattr(step.counterpart, "project_name", None) or getattr(step.item, "project_name", "")
    prefix = "%s-step-%d" % (section.assembly.name or "assembly", step.number)
    if step.context:
        context = [(child.item, child.name, child.location or Location()) for child in step.context]
    else:
        context = [(step.counterpart, step.counterpart_name, step.counterpart_location)]
    picture = _picture(
        project_name,
        prefix + "-exploded",
        [
            ("so-far", _group(project_name, prefix + "-so-far", CONTEXT_COLOR, context)),
            (
                "new",
                _group(
                    project_name, prefix + "-new", NEW_COLOR, [(step.item, step.item_name, step.exploded_location())]
                ),
            ),
        ],
    )
    return _keyed(
        picture,
        section,
        "guide-step-%d-exploded;%s;%s" % (step.number, _pulled(step.direction, step.distance), _COLORS),
    )


def fastened_assembly(section: GuideSection, step: GuideStep) -> Assembly:
    """What the fasteners of a step go into, in place, and the fasteners pulled out.

    Only the items the fasteners join are drawn - the item of the step, what
    each fastener is driven into and what it is driven through - so that the
    picture is of the joint and as close up as the joint allows, rather than of
    the whole of the assembly with screws too small to see on it.
    """
    project_name = getattr(step.item, "project_name", "")
    prefix = "%s-step-%d" % (section.assembly.name or "assembly", step.number)
    involved = {step.item_name}
    for fastener in step.fasteners:
        if fastener.target:
            involved.add(fastener.target)
        involved.update(fastener.through)
    held = [(child.item, child.name, child.location or Location()) for child in step.context if child.name in involved]
    held.append((step.item, step.item_name, step.location))
    fasteners = [(fastener.item, fastener.item_name, fastener.exploded_location()) for fastener in step.fasteners]
    picture = _picture(
        project_name,
        prefix + "-fastened",
        [
            ("held", _group(project_name, prefix + "-held", CONTEXT_COLOR, held)),
            ("fasteners", _group(project_name, prefix + "-fasteners", NEW_COLOR, fasteners)),
        ],
    )
    pulled = "/".join(_pulled(fastener.direction, fastener.distance) for fastener in step.fasteners)
    return _keyed(picture, section, "guide-step-%d-fastened;%s;%s" % (step.number, pulled, _COLORS))


# The colours of a step's picture, as its key says them: they are this module's
# rather than anything the package declares.
_COLORS = "colors=%s,%s" % (CONTEXT_COLOR, NEW_COLOR)


def _pulled(direction, distance) -> str:
    """Which way and how far something of a picture is pulled, as its key says it."""
    return "direction=%s;distance=%r" % (",".join("%r" % float(value) for value in direction), float(distance))


def _keyed(picture: Assembly, section: GuideSection, identity: str) -> Assembly:
    """A step's picture, keyed on the assembly the step is of and what the picture shows of it.

    A picture is put together here rather than declared, so it has no cache key
    of its own. What is in it is the assembly's own items, where the assembly
    puts them, chosen by the step; what is not is how far and which way some of
    them are pulled, which is worked out, and the colours. So those and the
    step, with the assembly's key, are what it is cached under, and drawing the
    book again draws nothing it has drawn before (see
    'Shape.get_artifact_key_async').
    """
    picture.derived_from = section.content
    picture.artifact_identity = identity
    return picture


#
# The documents
#


def bom_blocks(project, grouped, dir_path, level=2) -> list:
    """The bill of materials, as document blocks.

    The same section, whichever document asks for it: every part, every
    sub-assembly and every piece of software the assembly is made of, grouped by
    the package they come from and counted.
    """
    blocks = []
    for title, column, packages in (
        ("Sub-Assemblies", "Assembly", grouped["assemblies"]),
        ("Parts", "Part", grouped["parts"]),
    ):
        if not packages:
            continue
        blocks.append(doc.Heading(title, level=level))
        for package_name in sorted(packages.keys()):
            entries = packages[package_name]
            blocks.append(
                doc.Heading(
                    package_name,
                    level=level + 1,
                    url=package_document_link(project, package_name, dir_path),
                )
            )
            blocks.append(
                doc.Table(
                    columns=[column, "Count", "Description"],
                    aligns=["left", "right", "left"],
                    rows=[
                        [name, entries[name]["count"], entries[name].get("desc") or ""]
                        for name in sorted(entries.keys())
                    ],
                )
            )
    blocks += stock_blocks(project, grouped.get("stock") or {}, dir_path, level=level)
    blocks += software_blocks(project, grouped.get("software") or {}, dir_path, level=level)
    return blocks


def stock_blocks(project, packages, dir_path, level=2) -> list:
    """What the parts that are made are made from.

    The rest of the bill of materials is what goes into the assembly; this is
    what has to be procured so that the made parts can be made -- one piece per
    part, since cutting several parts out of one piece is a question of layout
    PartCAD does not answer yet (see 'partcad.procurement'). Each line says
    which parts it is for.
    """
    if not packages:
        return []
    blocks = [doc.Heading("Stock", level=level)]
    blocks.append(doc.Paragraph("What the manufactured parts are made from: one piece for each part made from it."))
    for package_name in sorted(packages.keys()):
        entries = packages[package_name]
        blocks.append(
            doc.Heading(
                package_name,
                level=level + 1,
                url=package_document_link(project, package_name, dir_path),
            )
        )
        blocks.append(
            doc.Table(
                columns=["Stock", "Count", "For", "Description"],
                aligns=["left", "right", "left", "left"],
                rows=[
                    [
                        name,
                        entries[name]["count"],
                        ", ".join(_short_name(project, made) for made in entries[name].get("for") or []),
                        entries[name].get("desc") or "",
                    ]
                    for name in sorted(entries.keys())
                ],
            )
        )
    return blocks


def _short_name(project, name: str) -> str:
    """An object's name, without its package where that is the document's own."""
    package_name, _, object_name = name.partition(":")
    return object_name if package_name == project.name else name


def software_blocks(project, packages, dir_path, level=2) -> list:
    """The software section of a bill of materials.

    Its own table rather than another column on the parts one, because what
    identifies a file is not what identifies a part. A part is identified by its
    name: whoever reads the BoM goes and gets that part. A firmware image is a
    file that its package can publish again tomorrow, so the line has to say
    *which* one - hence the revision of the source package on every row, beside
    the version and the hash the declaration pins.
    """
    if not packages:
        return []
    blocks = [doc.Heading("Software", level=level)]
    for package_name in sorted(packages.keys()):
        entries = packages[package_name]
        blocks.append(
            doc.Heading(
                package_name,
                level=level + 1,
                url=package_document_link(project, package_name, dir_path),
            )
        )
        blocks.append(
            # 'File hash' earns its column: the revision beside it identifies a
            # file the package carries, but a package with no source tree of its
            # own has no revision to report, and then a fetched image is
            # identified by its 'fileHash' or by nothing at all.
            doc.Table(
                columns=["Software", "Count", "Version", "Package revision", "File hash", "Description"],
                aligns=["left", "right", "left", "left", "left", "left"],
                rows=[
                    [
                        name,
                        entries[name]["count"],
                        # Not 'or ""': a numeric "version: 0" is a version.
                        "" if entries[name].get("version") is None else entries[name]["version"],
                        entries[name].get("revision") or "",
                        entries[name].get("fileHash") or "",
                        entries[name].get("desc") or "",
                    ]
                    for name in sorted(entries.keys())
                ],
            )
        )
    return blocks


def package_document_link(project, package_name, dir_path):
    """The path to another package's README.md, relative to 'dir_path'."""
    if project.ctx is None:
        return None
    other = project.ctx.get_project(package_name)
    config_dir = getattr(other, "config_dir", None)
    if config_dir is None:
        return None
    return relative_link(project, os.path.join(config_dir, "README.md"), dir_path)


def relative_link(project, path, dir_path):
    """The path to a file of this package tree, relative to 'dir_path'.

    Both the document being generated and the file it refers to have to live
    under the same root for a link to be produced. Packages served from the local
    cache, and documents generated outside of the root, are left unlinked: a path
    pointing out of the tree is of no use to whoever reads the generated
    document.
    """
    if not path or dir_path is None or project.ctx is None:
        return None

    # 'ctx.config_dir', not 'ctx.root_path': the latter may name the root
    # package's configuration file rather than the directory holding it.
    root_path = os.path.abspath(project.ctx.config_dir)
    try:
        for candidate in (path, dir_path):
            if os.path.relpath(os.path.abspath(candidate), root_path).startswith(os.pardir):
                return None
        return os.path.relpath(path, dir_path)
    except ValueError:
        # Not on the same drive (Windows); no relative path exists.
        return None


def package_author(project):
    """Who to credit for the package, if it says."""
    config = project.config_obj or {}
    for key in ("authors", "author", "poc", "maintainer"):
        value = config.get(key)
        if not value:
            continue
        if isinstance(value, (list, tuple)):
            return ", ".join(str(item) for item in value)
        return str(value)
    return None


async def build_readme_document_async(project, assembly, images: ImageSource, dir_path=None) -> doc.Document:
    """The markdown document of an assembly: what it is made of."""
    grouped = await assembly.get_bom_grouped_async(project.ctx)

    blocks = [doc.Heading(assembly.name, level=1)]
    if assembly.desc:
        blocks.append(doc.Paragraph(assembly.desc))
    blocks.append(doc.Properties([("Package", "`%s`" % project.name)]))

    image = await images.shape_image_async(assembly)
    if image is not None:
        blocks.append(doc.ImageRow([image]))

    blocks += bom_blocks(project, grouped, dir_path)

    return doc.Document(
        title=assembly.name,
        subtitle=assembly.desc,
        pages=[doc.Page(blocks=blocks, title=assembly.name)],
        footer=doc.GENERATED_BY,
    )


def build_readme_document(project, assembly, images: ImageSource, dir_path=None) -> doc.Document:
    return asyncio.run(build_readme_document_async(project, assembly, images, dir_path))


@dataclass
class Guide:
    """An instruction book, and the plan it was written from.

    'pages' says which page each item of the plan is explained on, by the
    item's id: what the IDE's Build tab shows when an item is selected, so that
    the step on screen and the page of the book are one and the same.
    """

    document: doc.Document
    plan: object = None
    pages: dict = field(default_factory=dict)


async def build_guide_document_async(
    ctx,
    project,
    assembly,
    images: ImageSource,
    dir_path=None,
    recursive=True,
    build_parts=True,
    choices=None,
) -> doc.Document:
    """The assembly instruction book of an assembly (see 'build_guide_async')."""
    guide = await build_guide_async(ctx, project, assembly, images, dir_path, recursive, build_parts, choices)
    return guide.document


async def build_guide_async(
    ctx,
    project,
    assembly,
    images: ImageSource,
    dir_path=None,
    recursive=True,
    build_parts=True,
    choices=None,
    force_manufacturing=False,
) -> Guide:
    """The assembly instruction book of an assembly, and the plan it follows.

    A title page, the bill of materials, then a page for every item of the
    build plan ('partcad.build_plan') in the order the plan lists them, and a
    page of links to close. The plan is the tree of the assembly's links, with
    an item before a link for whatever has to be made before that link can be
    added: so a part that is built is explained just before it is first needed,
    a sub-assembly is put together just before the link that adds it, and a
    thing used in many places is explained once, with how many to make.

    'recursive' puts the sub-assemblies that are built into the book, each with
    its own page and steps; without it the book is this assembly's own steps,
    with a sub-assembly added as the finished thing it is. 'build_parts' puts
    in a page for every part that is made rather than bought: what it is made
    from, the manufacturing instructions written out, and a drawing of the
    route a machine cuts it with where one can be produced. 'choices' are the
    user's Build vs Buy choices; this assembly itself is built, whatever they
    say, since its instructions are what was asked for. A line item that cannot
    be had at all ('build_plan.is_missing') is never built, so nothing is said
    about making it. 'force_manufacturing' is '--ignore-manufacturability',
    which takes the assembly and all of it as meant to be made.

    Every page is composed at the same time. What a page costs is its
    projections, one sandbox process each, and no page is an input to any other;
    the ceiling on all of it is the one 'images' holds (see
    '_sandbox_budget()'). 'asyncio.gather' returns results in the order it was
    given them, so the book reads in the order it was written in whatever order
    the projections land.
    """
    from . import build_plan

    tree, index = await build_plan.tree_async(ctx, assembly, force_manufacturing=force_manufacturing)
    # The assembly asked about is documented whatever is wrong with following
    # it: 'check_source' has decided it is one to write instructions for, and
    # what its steps fail to say is for 'pc test' and the Build vs Buy table to
    # report - an instruction book that refused to show the steps would hide
    # exactly what needs fixing.
    tree["build"] = bool(tree.get("children"))
    tree["manufacturable"] = True
    choices = dict(choices or {})
    choices[tree["name"]] = build_plan.BUILD
    plan = build_plan.plan(tree, choices, recursive=recursive, build_parts=build_parts)

    containers = [item for item in plan.walk() if item.type == build_plan.ITEM_ASSEMBLY]
    budget = _sandbox_budget()
    built = await asyncio.gather(
        *[
            _build_section(
                ctx,
                resolve_alias(ctx, index.objects[item.node["id"]]),
                top=item.id == build_plan.ROOT_ID,
                budget=budget,
            )
            for item in containers
        ]
    )
    sections = {}
    for item, section in zip(containers, built):
        section.count = item.count
        sections[item.container] = section

    grouped = await assembly.get_bom_grouped_async(ctx)

    # Which coroutine writes the page of which items, in the order the pages
    # are read in. The base of an assembly - the first link, which no step adds
    # - is explained on that assembly's own page rather than on one of its own.
    composers = []
    page_items = []
    same_page = {}
    # The first link of every step, by assembly and step number: the item whose
    # page the step's page is, which the other links of the step point at.
    first_link_of = {container: {} for container in sections}

    def visit(item):
        if item.type == build_plan.ITEM_ASSEMBLY:
            if item.id != build_plan.ROOT_ID:
                composers.append(_section_page(project, sections[item.container], images))
                page_items.append(item.id)
            for child in item.children:
                visit(child)
        elif item.type == build_plan.ITEM_LINK:
            section = sections[item.container]
            number = section.step_of_link.get(item.step, item.step)
            if number == 0:
                if item.container == build_plan.ROOT_ID:
                    composers.append(_section_page(project, section, images))
                    page_items.append(item.id)
                else:
                    same_page[item.id] = item.container
            elif number in first_link_of[item.container]:
                # A fastener driven in at the step of the item it holds: that
                # step's page is its page too.
                same_page[item.id] = first_link_of[item.container][number]
            else:
                first_link_of[item.container][number] = item.id
                composers.append(_step_page(section, section.steps[number - 1], images))
                page_items.append(item.id)
        elif item.type == build_plan.ITEM_MANUFACTURE:
            composers.append(_manufacture_page(ctx, project, item, index, images))
            page_items.append(item.id)

    visit(plan)

    composed = await asyncio.gather(_title_page(project, assembly, images, list(sections.values()), ctx), *composers)

    pages = [composed[0], doc.Page(title="Bill of Materials", blocks=_bom_page_blocks(project, grouped, dir_path))]
    page_of = {build_plan.ROOT_ID: 0}
    for item_id, page in zip(page_items, composed[1:]):
        page_of[item_id] = len(pages)
        pages.append(page)
    for item_id, other in same_page.items():
        page_of[item_id] = page_of[other]
    pages.append(_links_page(project, assembly, grouped, dir_path))

    document = doc.Document(
        title=assembly.name,
        subtitle=assembly.desc,
        pages=pages,
        footer=doc.GENERATED_BY,
    )
    return Guide(document=document, plan=plan, pages=page_of)


def build_guide_document(ctx, project, assembly, images: ImageSource, dir_path=None, **options) -> doc.Document:
    return asyncio.run(build_guide_document_async(ctx, project, assembly, images, dir_path, **options))


async def build_part_plan_async(ctx, project, part, images: ImageSource, choices=None) -> Guide:
    """What making a part takes, as pages: the IDE's Build tab for a part.

    The plan of a part is the chain of what it is made from, deepest first and
    the part itself last ('build_plan.plan'), and each item of it is explained
    on the same page an assembly's instruction book explains it on.
    """
    from . import build_plan

    tree, index = await build_plan.tree_async(ctx, part)
    plan = build_plan.plan(tree, choices)
    composed = await asyncio.gather(
        _part_title_page(project, part, images),
        *[_manufacture_page(ctx, project, item, index, images) for item in plan.children],
    )
    page_of = {build_plan.ROOT_ID: 0}
    for number, item in enumerate(plan.children, 1):
        page_of[item.id] = number
    document = doc.Document(
        title=part.name,
        subtitle=getattr(part, "desc", None),
        pages=list(composed),
        footer=doc.GENERATED_BY,
    )
    return Guide(document=document, plan=plan, pages=page_of)


@asynccontextmanager
async def guide_document_async(
    ctx, project, assembly, label, dir_path=None, ignore_manufacturability=False, reproducible=False, **options
):
    """The instruction book of an assembly, for as long as its pictures exist.

    A context manager rather than a plain call because the illustrations are
    files: most of them show something that is not an object of any package - a
    pair of items pulled apart - so they are rendered into a directory of their
    own and thrown away with it. Whoever asked for the document has to write it
    down, or embed the pictures, before the block ends.

    A module function and not a method of 'Project', although both of its callers
    are: '@telemetry.instrument()' wraps every callable a class holds, and the
    wrapper labels each positional argument by indexing the wrapped function's
    'co_varnames'. What 'asynccontextmanager' leaves in the class is contextlib's
    'helper(*args, **kwds)', whose 'co_varnames' has two entries, so a third
    positional argument raises IndexError before the document is ever built.

    'options' are those of 'build_guide_async': 'recursive', 'build_parts' and
    'choices'. 'reproducible' is not one of them: it is spelled out here and
    passed on by name, because what it reaches is the illustrations rather than
    the plan -- see 'RenderedImages'.
    """
    async with guide_async(
        ctx, project, assembly, label, dir_path, ignore_manufacturability, reproducible=reproducible, **options
    ) as guide:
        yield guide.document


@asynccontextmanager
async def guide_async(
    ctx, project, assembly, label, dir_path=None, ignore_manufacturability=False, reproducible=False, **options
):
    """'guide_document_async', yielding the plan and its pages with the document."""
    assembly = resolve_alias(ctx, assembly)
    check_source(assembly, ignore_manufacturability)

    with pc_logging.Action("Guide%s" % label, project.name, assembly.name):
        with tempfile.TemporaryDirectory() as assets_dir:
            images = RenderedImages(ctx, project, assets_dir, reproducible=reproducible)
            yield await build_guide_async(
                ctx, project, assembly, images, dir_path, force_manufacturing=ignore_manufacturability, **options
            )


@asynccontextmanager
async def part_plan_async(ctx, project, part, choices=None):
    """'build_part_plan_async', for as long as its pictures exist."""
    with pc_logging.Action("PlanData", project.name, part.name):
        with tempfile.TemporaryDirectory() as assets_dir:
            # Nothing asks for these to be reproducible: a plan is read on a
            # screen rather than checked in, so it gets the fast projection.
            images = RenderedImages(ctx, project, assets_dir)
            yield await build_part_plan_async(ctx, project, part, images, choices)


async def _title_page(project, assembly, images, sections, ctx=None):
    blocks = [doc.Heading(assembly.name, level=1)]

    image = await images.shape_image_async(assembly, alt=assembly.name)
    if image is not None:
        blocks.append(doc.ImageRow([image], height=0.5))

    blocks += _prose_blocks(assembly.desc)

    properties = [("Package", project.name)]
    author = package_author(project)
    if author:
        properties.append(("Author", author))
    properties.append(("Assemblies", str(len(sections))))
    # Every step that is done, which counts a section that is made twice twice:
    # the number of the steps written down is not what anybody does.
    properties.append(("Steps", str(sum(len(section.steps) * section.count for section in sections))))
    size = await _size_words(ctx, assembly)
    if size:
        properties.append(("Size", size))
    blocks.append(doc.Properties(properties))
    blocks.append(doc.Paragraph("Generated by PartCAD"))

    return doc.Page(title=assembly.name, blocks=blocks)


async def _size_words(ctx, shape) -> Optional[str]:
    """How big a shape is, along X, Y and Z, in millimetres and inches."""
    if ctx is None:
        return None
    try:
        box = await shape.get_bounding_box_async(ctx)
    except Exception as e:  # pylint: disable=broad-except
        pc_logging.debug("Could not measure %s: %s" % (getattr(shape, "name", "?"), e))
        return None
    if not box:
        return None
    sizes = [box[3] - box[0], box[4] - box[1], box[5] - box[2]]
    return "%s mm (%s in.), along X, Y and Z" % (
        " x ".join("%.0f" % size for size in sizes),
        " x ".join(_number_words(round(size / 25.4, 2)) for size in sizes),
    )


def _bom_page_blocks(project, grouped, dir_path):
    blocks = [doc.Heading("Bill of Materials", level=1)]
    blocks += bom_blocks(project, grouped, dir_path, level=2)
    return blocks


async def _part_title_page(project, part, images):
    blocks = [doc.Heading(part.name, level=1)]
    image = await images.shape_image_async(part, alt=part.name)
    if image is not None:
        blocks.append(doc.ImageRow([image], height=0.5))
    blocks += _prose_blocks(getattr(part, "desc", None))
    blocks.append(doc.Properties([("Package", project.name)]))
    return doc.Page(title=part.name, blocks=blocks)


async def _manufacture_page(ctx, project, item, index, images: ImageSource):
    """How to make one part: what it is made from, the instructions, the route.

    The manufacturing instructions written out in full (see
    'partcad.manufacturing_instructions') come first, since they are what the
    reader follows; then the drawing of the route a machine cuts it with, where
    the part declares a job and a route can be produced (see 'cam_preview').
    Primitive on purpose: until PartCAD can draw each method, text and the
    route are what there is to show.
    """
    from .manufacturing_instructions import describe
    from .part_config import PartConfiguration

    node = item.node or {}
    part = index.objects.get(node.get("id"))
    name = item.name
    stock = node.get("stock") or {}

    heading = _short_name(project, name)
    blocks = [
        doc.Heading(
            _label(heading),
            level=1,
            kicker="Make" if item.count <= 1 else "Make %d" % item.count,
        )
    ]
    if part is None:
        blocks.append(doc.Paragraph("%s is not found, so there is nothing to say about making it." % name))
        return doc.Page(title=item.title, blocks=blocks)

    picture, routes = await asyncio.gather(
        images.shape_image_async(part, alt=name),
        _route_images(ctx, part, images),
    )
    if picture is not None:
        blocks.append(doc.ImageRow([picture], height=0.25))
    blocks += _prose_blocks(getattr(part, "desc", None))
    properties = [("Package", part.project_name), ("Needed", str(item.count))]
    if _parameters(name):
        properties.append(("Size", _parameters(name)))
    if stock.get("name"):
        properties.append(("Made from", stock["name"]))
    blocks.append(doc.Properties(properties))

    data = PartConfiguration.get_manufacturing_data(part)
    for line in describe(data, stock.get("name")):
        blocks.append(doc.Paragraph(line))

    for image, note in routes:
        if image is not None:
            blocks.append(doc.ImageRow([image], height=0.45))
        if note:
            blocks.append(doc.Paragraph(note))
    return doc.Page(title=item.title, blocks=blocks)


async def _route_images(ctx, part, images: ImageSource) -> list:
    """The routes a machine cuts the part with, drawn: [(image or None, note)].

    One per machine the part names that is routed (a saw is not: its cuts are
    the instructions above), or one for the part as a whole when it declares a
    job without naming a machine. Nothing for a part that says nothing about
    being cut. A route that cannot be produced is a note rather than a failure
    of the page: the instructions above it still stand.
    """
    from . import cam as pc_cam
    from . import cam_preview
    from .part_config import PartConfiguration
    from .part_config_manufacturing import ROUTED_MACHINES

    directory = getattr(images, "directory", None)
    if ctx is None or directory is None or not pc_cam.declares_job(part):
        return []
    data = PartConfiguration.get_manufacturing_data(part)
    machines = [kind for kind in data.machine_choices() if kind in ROUTED_MACHINES and data.machines[kind].declared]
    budget = getattr(images, "_budget", None) or _sandbox_budget()

    async def one(machine):
        label = "%s:%s" % (part.project_name, part.name) + ("" if machine is None else " (%s)" % machine)
        output_dir = tempfile.mkdtemp(prefix="route-", dir=directory)
        try:
            async with budget:
                result = await part.route_async(ctx, output_dir=output_dir, machine=machine)
            with open(result["filepath"]) as f:
                text = f.read()
        except Exception as e:  # pylint: disable=broad-except
            pc_logging.debug("No route for %s: %s" % (label, e))
            return None, "The route for %s could not be produced: %s" % (label, str(e).strip().splitlines()[0])
        drawing, stats = cam_preview.svg(text)
        if drawing is None:
            return None, None
        path = os.path.join(directory, _slug("route-" + label) + ".svg")
        with open(path, "w") as f:
            f.write(drawing)
        caption = "The route%s, seen from above: %d cutting moves, %.0f mm in the cut; rapid moves dashed." % (
            "" if machine is None else " on the %s" % machine,
            stats["cuts"],
            stats["cut_length"],
        )
        return doc.Image(file=path, alt="Route of %s" % label, caption=caption), None

    return list(await asyncio.gather(*[one(machine) for machine in machines or [None]]))


async def _section_pages(project, section: GuideSection, images: ImageSource, section_count=1):
    """An assembly's own page and a page for each of its steps, in that order."""
    # The assembly's own picture and every one of its steps at once: they are
    # separate projections of separate things, and which page each lands on is
    # decided here rather than by whichever finished first.
    page, *step_pages = await asyncio.gather(
        _section_page(project, section, images),
        *[_step_page(section, step, images) for step in section.steps],
    )
    return [page] + step_pages


def _section_kicker(section: GuideSection) -> str:
    """What a page of a section belongs to, in a few words: its name, and how many to make."""
    label = _label(section.name)
    return label if section.count <= 1 else "%s - make %d" % (label, section.count)


async def _section_page(project, section: GuideSection, images: ImageSource):
    """An assembly's own page: what it looks like together, what goes into it, and what to start with."""
    image = await images.shape_image_async(section.assembly, alt=section.name)

    label = _label(section.name)
    if section.top:
        blocks = [doc.Heading(label, level=1)]
    else:
        blocks = [
            doc.Heading(
                label,
                level=1,
                kicker="Sub-assembly" if section.count <= 1 else "Sub-assembly - make %d" % section.count,
            )
        ]

    if image is not None:
        # The top assembly's picture is on the cover already, at half a page.
        blocks.append(doc.ImageRow([image], height=0.3 if section.top else 0.4))

    blocks += _prose_blocks(getattr(section.assembly, "desc", None))
    properties = [("Package", section.assembly.project_name)]
    if _parameters(section.name):
        properties.append(("Size", _parameters(section.name)))
    properties.append(("Steps", str(len(section.steps))))
    if section.count > 1:
        properties.append(("Needed", "%d" % section.count))
    blocks.append(doc.Properties(properties))
    if section.count > 1:
        blocks.append(
            doc.Paragraph(
                "The build needs %d of these. Repeat this section %d times - the steps are the same every time."
                % (section.count, section.count)
            )
        )
    needed = _needed_rows(project, section)
    if needed:
        blocks.append(doc.Heading("What goes into it" if section.count <= 1 else "What goes into one", level=2))
        blocks.append(
            doc.Table(columns=["Item", "Count", "Description"], aligns=["left", "right", "left"], rows=needed)
        )
    if section.base_name:
        blocks.append(doc.Paragraph("Start with %s." % section.base_name))
        blocks += _prose_blocks(section.base_description)

    return doc.Page(title=label, blocks=blocks)


def _needed_rows(project, section: GuideSection) -> list:
    """What one of a section's assembly is put together from, counted: its own links, not theirs.

    Its sub-assemblies are a line each, as the finished things they are by the
    time this one is put together: what is inside them is on their own page.
    """
    counts = {}
    for child in section.children:
        item = child.item
        key = _object_key(item)
        if key not in counts:
            counts[key] = [item, 0]
        counts[key][1] += 1
    rows = []
    for item, count in counts.values():
        name = _short_name(project, "%s:%s" % (getattr(item, "project_name", ""), getattr(item, "name", "")))
        description = getattr(item, "desc", None) or ""
        size = _parameters(name)
        if size:
            description = "%s (%s)" % (description, size) if description else size
        rows.append([_label(name), count, " ".join(description.split())])
    return rows


async def _step_page(section: GuideSection, step: GuideStep, images: ImageSource):
    """One step: the parts it needs, the item going on, and the fasteners going in.

    Laid out by what the step adds, in the way a printed instruction book is:

    * the parts a person has to pick out - every fastener, and the item itself
      when it is small next to the whole (see '_is_small') - in a box of their
      own, with how many. A board or a panel is what the picture is of, and
      shown again on its own it would only take room; a screw is a few pixels
      of that picture, and the box is where it can be seen, and counted;
    * the item going onto what is there already: everything placed before the
      step in grey, and the item in blue, held off the joint along which it
      goes on - the assembly so far, rather than the one part it is joined
      to, because that is what the reader has in front of them;
    * when it is fastened, the fasteners going in: only the parts they join,
      in place, and the fasteners pulled out of their holes along the line
      they go in by.

    The words are the node's description, for whoever builds it, and what the
    model says about the joint below them, set apart, for whoever checks the
    book against the model.
    """
    total = len(section.steps)
    small = await _small_items(section, step)
    position_view = images.shape_image_async(
        exploded_assembly(section, step),
        key="%s-step-%d-exploded" % (section.name, step.number),
        alt="%s going on" % step.item_name,
        annotations=[step.gap] if step.gap else None,
        along=step.direction,
        view=section.view,
    )
    fasten_view = None
    if step.fasteners:
        fasten_view = images.shape_image_async(
            fastened_assembly(section, step),
            key="%s-step-%d-fastened" % (section.name, step.number),
            alt="%s fastened" % step.item_name,
            annotations=[fastener.gap for fastener in step.fasteners if fastener.gap] or None,
            along=step.fasteners[0].direction,
            view=view_facing([fastener.direction for fastener in step.fasteners]),
        )
    thumbnails = [
        images.shape_image_async(item, alt=label, caption="%d \u00d7 %s" % (count, label))
        for item, count, label in small
    ]
    position, fastened, *pictures = await asyncio.gather(position_view, fasten_view or _nothing(), *thumbnails)

    blocks = [doc.Heading("Step %d of %d" % (step.number, total), level=1, kicker=_section_kicker(section))]
    pictures = [picture for picture in pictures if picture is not None]
    if pictures:
        blocks.append(doc.ImageRow(pictures, height=0.09, boxed=True, title="Parts for this step"))

    said = _prose_blocks(step.item_description)
    blocks += said or [doc.Paragraph(step.description())]
    blocks += [doc.Paragraph(sentence) for sentence in step.also_sentences()]
    if step.fasteners:
        blocks += _fastener_blocks(step)

    # Positioning and fastening are two things done one after the other, and
    # side by side they read in that order: left to right, as the text does.
    row = [picture for picture in (position, fastened) if picture is not None]
    if step.fasteners and len(row) == 2:
        position.caption, fastened.caption = "1. Put it in place", "2. Fasten it"
        blocks.append(doc.ImageRow(row, height=0.5))
    elif row:
        blocks.append(doc.ImageRow(row, height=0.55))

    details = ([step.joint_detail()] if said and step.joint_detail() else []) + step.also_detail()
    details += _fastener_details(step)
    blocks += [doc.Paragraph(detail, style=doc.PARAGRAPH_DETAIL) for detail in details]

    # Marked as a note, because it is one: a "comment" is context around the
    # step and never the step itself, and the reader has to be able to tell
    # which of the paragraphs is the thing to do.
    for comment in [step.comment] + [fastener.comment for fastener in step.fasteners]:
        paragraphs = _prose(comment)
        if paragraphs:
            blocks.append(doc.Paragraph("Note: %s" % paragraphs[0], style=doc.PARAGRAPH_NOTE))
            blocks += [doc.Paragraph(paragraph, style=doc.PARAGRAPH_NOTE) for paragraph in paragraphs[1:]]

    return doc.Page(title="%s: step %d" % (_label(section.name), step.number), blocks=blocks)


async def _nothing():
    return None


def _fastener_groups(step: GuideStep) -> list:
    """A step's fasteners as '(the first of them, all of them)' per kind, in the order they go in."""
    groups = {}
    for fastener in step.fasteners:
        groups.setdefault(_object_key(fastener.item), []).append(fastener)
    return [(fasteners[0], fasteners) for fasteners in groups.values()]


def _fastener_blocks(step: GuideStep) -> list:
    """What the fasteners of a step say about driving them in, or a sentence saying how many."""
    said = []
    for fastener in step.fasteners:
        for paragraph in _prose(fastener.description):
            if paragraph not in said:
                said.append(paragraph)
    if said:
        return [doc.Paragraph(paragraph) for paragraph in said]
    return [
        doc.Paragraph("Fasten it with %d \u00d7 %s." % (len(fasteners), _label(first.item.name)))
        for first, fasteners in _fastener_groups(step)
    ]


def _fastener_details(step: GuideStep) -> list:
    """The model's account of a step's fasteners: how many of what go into what, through what."""
    details = []
    for first, fasteners in _fastener_groups(step):
        into = []
        for fastener in fasteners:
            if fastener.target and fastener.target not in into:
                into.append(fastener.target)
        through = []
        for fastener in fasteners:
            for name in fastener.through:
                if name not in through:
                    through.append(name)
        text = "Fasteners: %d \u00d7 %s" % (len(fasteners), _label(first.item.name))
        if into:
            text += " into %s" % ", ".join(into)
        if through:
            text += " through %s" % ", ".join(through)
        how = _how_words(first.how)
        details.append(text + (", " + how if how else "") + ".")
    return details


async def _small_items(section: GuideSection, step: GuideStep) -> list:
    """The items a step adds that are shown on their own, as '(item, count, label)'.

    Every kind of fastener, with how many go in; and the item of the step when
    it is small next to the finished assembly. See '_step_page' for why.
    """
    items = []
    if await _is_small(section, step.item):
        items.append((step.item, 1, _label(step.item.name)))
    for first, fasteners in _fastener_groups(step):
        items.append((first.item, len(fasteners), _label(first.item.name)))
    return items


async def _is_small(section: GuideSection, item) -> bool:
    """Whether an item is small enough next to its finished assembly to be hard to pick out in it."""
    if section.size is None:
        return False
    try:
        size = await item.get_max_dimension_async(section.ctx)
    except Exception:  # pylint: disable=broad-except
        return False
    return size is not None and size < SMALL_FRACTION * section.size


def _counterpart_key(section: GuideSection, step: GuideStep):
    """A name for the counterpart's picture.

    An item is its own picture wherever it is used; the partial assembly of a
    step is not, so it is keyed by the step it belongs to.

    That includes an assembly embedded in the ASSY file's 'links:'. It used to be
    keyed by the step too, being a 'child' as the partial one is, which drew it
    twice at once - here and on its own section's page - as two projections of
    one object under one action name (see 'logging_ansi_terminal.action_key').
    """
    if step.counterpart_so_far:
        return "%s-step-%d-so-far" % (section.name, step.number)
    return None


def _links_page(project, assembly, grouped, dir_path):
    blocks = [doc.Heading("Links", level=1)]

    items = []
    package_url = (project.config_obj or {}).get("url")

    assembly_link = relative_link(project, getattr(assembly, "path", None), dir_path) or package_url
    if assembly_link:
        items.append(("This assembly: %s" % assembly.name, assembly_link))

    this_package = package_url or package_document_link(project, project.name, dir_path)
    if this_package:
        items.append(("This package: %s" % project.name, this_package))

    for package_name, count in _supplier_packages(project, grouped):
        link = _package_url(project, package_name) or package_document_link(project, package_name, dir_path)
        if link:
            items.append(("%s (%d parts)" % (package_name, count), link))

    items.append(("PartCAD", doc.PARTCAD_URL))

    blocks.append(doc.LinkList(items))
    return doc.Page(title="Links", blocks=blocks)


def _supplier_packages(project, grouped):
    """The packages that supply enough of this assembly to be worth linking to."""
    counts = {}
    # Parts and sub-assemblies only: this counts what somebody has to source,
    # and the label below says "parts". Where a package's software comes from is
    # already a link of its own, in the software section of the BoM.
    for kind in ("parts", "assemblies", "stock"):
        for package_name, entries in (grouped.get(kind) or {}).items():
            if package_name == project.name:
                continue
            counts[package_name] = counts.get(package_name, 0) + sum(entry["count"] for entry in entries.values())
    return sorted(
        ((name, count) for name, count in counts.items() if count >= SUPPLIER_LINK_THRESHOLD),
        key=lambda item: (-item[1], item[0]),
    )


def _package_url(project, package_name):
    if project.ctx is None:
        return None
    other = project.ctx.get_project(package_name)
    if other is None:
        return None
    return (getattr(other, "config_obj", None) or {}).get("url")
