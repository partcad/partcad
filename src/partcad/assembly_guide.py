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

from . import document as doc
from . import logging as pc_logging
from .assembly import Assembly
from .exception import NotAnAssemblyFileError, NotManufacturableError
from .geom import Location
from .render import render_cfg_merge

# How far apart an exploded view pulls the two items of a step, as a fraction of
# the largest dimension of the two, unless the step says otherwise.
EXPLODED_FRACTION = 0.5

# What to space two items by when neither of them can be measured (an empty
# shape, or a runtime that failed to hand a bounding box back). Small enough to
# be harmless, large enough to be visible.
FALLBACK_EXPLODED_DISTANCE = 10.0

# How many parts a package has to contribute before the guide links to it. The
# document is for whoever is assembling the thing, and a package that supplies a
# single screw is not where they will go looking for anything.
SUPPLIER_LINK_THRESHOLD = 3

# How many times an alias is followed before giving up on a cycle.
MAX_ALIAS_DEPTH = 16

# The formats an assembly instruction book is generated in.
GUIDE_FORMATS = ("pdf", "html")


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


class ImageSource:
    """Where the pictures of a document come from."""

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None):
        return None

    def shape_image(self, shape, key=None, alt=None, caption=None, annotations=None):
        # Inherited by every image source, so each of them offers both forms.
        return asyncio.run(self.shape_image_async(shape, key, alt, caption, annotations))


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

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None):
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
    """

    def __init__(self, ctx, project, directory):
        self.ctx = ctx
        self.project = project
        self.directory = directory
        self.rendered = {}

    async def shape_image_async(self, shape, key=None, alt=None, caption=None, annotations=None):
        if key is None:
            key = "%s:%s" % (shape.project_name, shape.name)

        path = self.rendered.get(key)
        if path is None:
            path = os.path.join(self.directory, _slug(key) + ".svg")
            os.makedirs(self.directory, exist_ok=True)
            await shape.render_svg_somewhere_async(
                ctx=self.ctx,
                project=self.project,
                filepath=path,
                annotations=annotations,
            )
            if not os.path.exists(path):
                pc_logging.warning("Failed to render the illustration of %s" % key)
                return None
            self.rendered[key] = path

        return doc.Image(file=path, alt=alt or key, caption=caption)


def _slug(text):
    """A file name that stands for an object name."""
    return re.sub(r"[^A-Za-z0-9_.-]+", "-", text).strip("-") or "image"


#
# The steps of an assembly
#


@dataclass
class GuideStep:
    """One item joined to one other item."""

    number: int
    item: object
    item_name: str
    location: Location
    counterpart: object
    counterpart_name: str
    counterpart_location: Location
    connection: Optional[dict] = None
    # Where the two are pulled apart to, and the line that shows the gap.
    direction: tuple = (0.0, 0.0, 1.0)
    distance: float = FALLBACK_EXPLODED_DISTANCE
    gap: Optional[tuple] = None

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


@dataclass
class GuideSection:
    """One assembly and the steps it is put together in."""

    assembly: Assembly
    name: str
    steps: list = field(default_factory=list)
    top: bool = False


async def collect_sections_async(ctx, assembly) -> list:
    """Every assembly that has to be built, in the order it has to be built in.

    Sub-assemblies come before the assembly that uses them - they have to exist
    before it can be put together - and the top level assembly comes last. An
    assembly used more than once is documented once.
    """
    sections = []
    seen = set()
    await _collect_section(ctx, assembly, sections, seen, top=True)
    return sections


def collect_sections(ctx, assembly) -> list:
    return asyncio.run(collect_sections_async(ctx, assembly))


async def _collect_section(ctx, assembly, sections, seen, top=False):
    await assembly.do_instantiate()

    key = _assembly_key(assembly)
    if key in seen:
        return
    seen.add(key)

    content = _step_source(assembly)
    for child in content.children:
        if isinstance(child.item, Assembly):
            await _collect_section(ctx, child.item, sections, seen)

    sections.append(await _build_section(ctx, assembly, content, top))


def _step_source(assembly):
    """The assembly whose children are the items that get assembled.

    The root node of an ASSY file is itself a container, so the assembly a
    package declares holds one embedded assembly with everything inside it. That
    wrapper is neither a step nor a sub-assembly of its own - it is the same
    thing under another name - so it is looked through rather than documented.
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


async def _build_section(ctx, assembly, content=None, top=False):
    if content is None:
        content = _step_source(assembly)
    section = GuideSection(assembly=assembly, name=_display_name(assembly), top=top)

    placed = []
    for child in content.children:
        if not placed:
            # The first item is what everything else is added to; there is
            # nothing yet to connect it to.
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
            connection=child.connection,
        )
        await _resolve_step_geometry(ctx, step)
        section.steps.append(step)
        placed.append(child)

    return section


def _counterpart(assembly, placed, child):
    """What the item of this step is joined to.

    A step that names what it connects to is joined to that item alone. A step
    that only gives a location is joined to everything placed so far, which is
    what the person following the instructions has in their hands at that point.
    """
    target = (child.connection or {}).get("target")
    if target is not None:
        for candidate in placed:
            if candidate.name == target:
                return candidate.item, candidate.name or candidate.item.name, candidate.location or Location()

    if len(placed) == 1:
        only = placed[0]
        return only.item, only.name or only.item.name, only.location or Location()

    partial = Assembly(
        assembly.project_name,
        {
            "name": "%s-step-%d" % (assembly.name or "assembly", len(placed)),
            "child": True,
            "cache": False,
        },
    )
    # Nothing instantiates this one: it is populated here, once, and never
    # re-read from a configuration file.
    partial.instantiate = lambda _: True
    for candidate in placed:
        partial.add(candidate.item, candidate.name, candidate.location or Location())
    return partial, "the sub-assembly so far", Location()


async def _resolve_step_geometry(ctx, step: GuideStep):
    """How far apart to pull the two items of a step, and which way.

    The direction comes from the joint when there is one: the two were mated
    face to face, so the item backs out along the normal of the port it was
    connected to. Without a joint there is only the geometry to go by, and the
    item backs out along the line between the two centers.
    """
    connection = step.connection or {}

    item_center = await _placed_center(ctx, step.item, step.location)
    counterpart_center = await _placed_center(ctx, step.counterpart, step.counterpart_location)
    away = [item_center[i] - counterpart_center[i] for i in range(3)]

    direction = _normalized(connection.get("direction")) or _normalized(away)
    if direction is None:
        direction = (0.0, 0.0, 1.0)
    # A port's normal is an axis, not a side: which end of it points out of the
    # material depends on how the port was declared. Take the end that moves the
    # item away from what it is being joined to, so that an exploded view always
    # pulls the two apart rather than pushing one through the other.
    if sum(direction[i] * away[i] for i in range(3)) < 0:
        direction = tuple(-value for value in direction)
    step.direction = direction

    distance = connection.get("exploded")
    if distance is None:
        dimensions = [
            await step.item.get_max_dimension_async(ctx),
            await step.counterpart.get_max_dimension_async(ctx),
        ]
        dimensions = [dimension for dimension in dimensions if dimension]
        distance = EXPLODED_FRACTION * max(dimensions) if dimensions else FALLBACK_EXPLODED_DISTANCE
    step.distance = float(distance)

    # The line that shows the gap runs from where the two meet to where the item
    # has been moved to. Without a joint to point at, it runs from the item's own
    # center, which is where it came from.
    start = connection.get("point") or item_center
    end = [start[i] + step.direction[i] * step.distance for i in range(3)]
    step.gap = (list(start), end)


async def _placed_center(ctx, shape, location):
    """The center of a shape's bounding box, where the assembly puts it."""
    box = await shape.get_bounding_box_async(ctx)
    if box is None:
        center = (0.0, 0.0, 0.0)
    else:
        center = ((box[0] + box[3]) / 2.0, (box[1] + box[4]) / 2.0, (box[2] + box[5]) / 2.0)
    return location.transform_point(center) if location is not None else center


def _normalized(vector):
    if not vector:
        return None
    length = math.sqrt(sum(float(value) ** 2 for value in vector))
    if length < 1e-9:
        return None
    return tuple(float(value) / length for value in vector)


def exploded_assembly(step: GuideStep) -> Assembly:
    """The two items of a step, connected but held apart."""
    project_name = getattr(step.counterpart, "project_name", None) or getattr(step.item, "project_name", "")
    pair = Assembly(
        project_name,
        {
            "name": "step-%d-exploded" % step.number,
            "child": True,
            "cache": False,
        },
    )
    pair.instantiate = lambda _: True
    pair.add(step.counterpart, step.counterpart_name, step.counterpart_location)
    pair.add(step.item, step.item_name, step.exploded_location())
    return pair


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
    blocks += software_blocks(project, grouped.get("software") or {}, dir_path, level=level)
    return blocks


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
            doc.Table(
                columns=["Software", "Count", "Version", "Package revision", "Description"],
                aligns=["left", "right", "left", "left", "left"],
                rows=[
                    [
                        name,
                        entries[name]["count"],
                        entries[name].get("version") or "",
                        entries[name].get("revision") or "",
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


async def build_guide_document_async(ctx, project, assembly, images: ImageSource, dir_path=None) -> doc.Document:
    """The assembly instruction book of an assembly.

    A title page, the bill of materials, then every assembly - sub-assemblies
    first - with a page showing what it should look like once it is together and
    a page for each of its steps, and a page of links to close.
    """
    sections = await collect_sections_async(ctx, assembly)
    grouped = await assembly.get_bom_grouped_async(ctx)

    pages = [await _title_page(project, assembly, images, sections)]
    pages.append(doc.Page(title="Bill of Materials", blocks=_bom_page_blocks(project, grouped, dir_path)))

    for section in sections:
        pages += await _section_pages(project, section, images, len(sections))

    pages.append(_links_page(project, assembly, grouped, dir_path))

    return doc.Document(
        title=assembly.name,
        subtitle=assembly.desc,
        pages=pages,
        footer=doc.GENERATED_BY,
    )


def build_guide_document(ctx, project, assembly, images: ImageSource, dir_path=None) -> doc.Document:
    return asyncio.run(build_guide_document_async(ctx, project, assembly, images, dir_path))


@asynccontextmanager
async def guide_document_async(ctx, project, assembly, label, dir_path=None, ignore_manufacturability=False):
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
    """
    assembly = resolve_alias(ctx, assembly)
    check_source(assembly, ignore_manufacturability)

    with pc_logging.Action("Guide%s" % label, project.name, assembly.name):
        with tempfile.TemporaryDirectory() as assets_dir:
            images = RenderedImages(ctx, project, assets_dir)
            yield await build_guide_document_async(ctx, project, assembly, images, dir_path)


async def _title_page(project, assembly, images, sections):
    blocks = [doc.Heading(assembly.name, level=1)]

    image = await images.shape_image_async(assembly, alt=assembly.name)
    if image is not None:
        blocks.append(doc.ImageRow([image], height=0.5))

    if assembly.desc:
        blocks.append(doc.Paragraph(assembly.desc))

    properties = [("Package", project.name)]
    author = package_author(project)
    if author:
        properties.append(("Author", author))
    properties.append(("Assemblies", str(len(sections))))
    properties.append(("Steps", str(sum(len(section.steps) for section in sections))))
    blocks.append(doc.Properties(properties))
    blocks.append(doc.Paragraph("Generated by PartCAD"))

    return doc.Page(title=assembly.name, blocks=blocks)


def _bom_page_blocks(project, grouped, dir_path):
    blocks = [doc.Heading("Bill of Materials", level=1)]
    blocks += bom_blocks(project, grouped, dir_path, level=2)
    return blocks


async def _section_pages(project, section: GuideSection, images: ImageSource, section_count):
    title = "Assembly: %s" % section.name if not section.top else section.name
    blocks = [doc.Heading(title, level=1)]

    image = await images.shape_image_async(section.assembly, alt=section.name)
    if image is not None:
        blocks.append(doc.ImageRow([image], height=0.5))

    desc = getattr(section.assembly, "desc", None)
    if desc:
        blocks.append(doc.Paragraph(desc))
    blocks.append(
        doc.Properties(
            [
                ("Package", section.assembly.project_name),
                ("Steps", str(len(section.steps))),
            ]
        )
    )
    if section.top and section_count > 1:
        blocks.append(doc.Paragraph("Assemble the sub-assemblies documented above before starting on this one."))

    pages = [doc.Page(title=section.name, blocks=blocks)]

    for step in section.steps:
        pages.append(await _step_page(section, step, images))

    return pages


async def _step_page(section: GuideSection, step: GuideStep, images: ImageSource):
    blocks = [doc.Heading("%s: step %d of %d" % (section.name, step.number, len(section.steps)), level=1)]

    row = []
    item_image = await images.shape_image_async(step.item, alt=step.item_name, caption=step.item_name)
    if item_image is not None:
        row.append(item_image)
    counterpart_image = await images.shape_image_async(
        step.counterpart,
        key=_counterpart_key(section, step),
        alt=step.counterpart_name,
        caption=step.counterpart_name,
    )
    if counterpart_image is not None:
        row.append(counterpart_image)
    if row:
        blocks.append(doc.ImageRow(row, height=0.3))

    blocks.append(doc.Paragraph(step.description()))

    exploded = await images.shape_image_async(
        exploded_assembly(step),
        key="%s-step-%d-exploded" % (section.name, step.number),
        alt="%s exploded" % step.item_name,
        caption="Exploded view: the two are shown %.1fmm apart." % step.distance,
        annotations=[step.gap] if step.gap else None,
    )
    if exploded is not None:
        blocks.append(doc.ImageRow([exploded], height=0.45))

    return doc.Page(title="%s: step %d" % (section.name, step.number), blocks=blocks)


def _counterpart_key(section: GuideSection, step: GuideStep):
    """A name for the counterpart's picture.

    A named item is its own picture wherever it is used; the partial assembly of
    a step is not, so it is keyed by the step it belongs to.
    """
    if isinstance(step.counterpart, Assembly) and step.counterpart.config.get("child", False):
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
    for kind in ("parts", "assemblies"):
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
