#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'material' a part is made of.

A part's ``material`` parameter is one of the MCFTT parameters: it does not
describe the shape, it says what the shape is to be made out of. Until now it
was a plain string, matched against whatever a manufacturing provider happened
to call the same substance, and the packages that catalogued materials
(``//pub/std/manufacturing/material/...``) declared them in a section PartCAD
did not read. This module is the object that string now points at.

A 'Material' is deliberately **not** a 'Shape', for the same reason 'Software'
is not: there is nothing to tessellate, render, export or measure. PLA is not a
thing with geometry, it is a set of facts about a substance - what it is
formally called, how dense it is, what it is good and bad at - that the things
with geometry refer to. Density is the one of those facts PartCAD can compute
with today (mass = volume x density), and it is why the value is carried in the
units the rest of PartCAD works in rather than the ones a datasheet prints.

Materials are addressed like every other object, as '<package>:<name>', so a
part in one package names a material catalogued in another exactly as it names
an interface or a sketch. That is the whole point: 'lookup()' here is what turns
'//pub/std/manufacturing/material/plastic:pla' from a string nobody resolves
into the object a provider, a bill of materials or a mass calculation can ask
questions of.
"""

import typing

from . import logging as pc_logging
from . import telemetry
from .utils import resolve_resource_path


@telemetry.instrument()
class Material:
    """One material of a package.

    'density' is in g/mm^3, the units every length in PartCAD is already in, so
    that a mass falls out of a volume without a conversion nobody remembers to
    apply. Datasheets quote g/cm^3, which is 1000x larger; a declaration is
    taken at face value, and 'density_g_cm3' exists for reporting it back the
    way it was read.
    """

    name: str
    project_name: str
    desc: str
    kind: str = "material"
    config: dict[str, typing.Any]
    errors: list[str]

    def __init__(self, name: str, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        self.name = name
        self.project_name = project_name
        self.config = config
        # Stripped the way 'Software' and 'Shape' strip theirs: a folded YAML
        # scalar ends with a newline, and that newline reaches a generated
        # README as a trailing line break inside a table cell.
        desc = config.get("desc", "")
        self.desc = desc.strip() if isinstance(desc, str) else desc
        self.errors = []

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        pc_logging.error("%s: %s: %s" % (self.project_name, self.name, msg))

    @property
    def formal(self) -> typing.Optional[str]:
        """The short formal name ('PLA'), or None.

        Falls back to nothing rather than to 'name': the object's own name is
        the address it is reached at, which a package is free to spell however
        it likes, and reporting it as though the package had stated a formal
        name would be inventing one.
        """
        return self.config.get("formal")

    @property
    def full(self) -> typing.Optional[str]:
        """The full name of the substance ('Polylactic Acid'), or None."""
        return self.config.get("full")

    @property
    def url(self) -> typing.Optional[str]:
        return self.config.get("url")

    @property
    def density(self) -> typing.Optional[float]:
        """Density in g/mm^3, or None if the package did not state one."""
        value = self.config.get("density")
        return None if value is None else float(value)

    @property
    def density_g_cm3(self) -> typing.Optional[float]:
        """The same density in the units datasheets quote."""
        density = self.density
        return None if density is None else density * 1000.0

    @property
    def tags(self) -> list[str]:
        """What the material is good at, as the package chose to say it.

        Free-form on purpose. There is no controlled vocabulary of material
        properties that survives contact with real catalogues, and inventing one
        here would only mean packages could not say what they mean.
        """
        tags = self.config.get("tags")
        if not tags:
            return []
        if isinstance(tags, str):
            return [tags]
        return [str(tag) for tag in tags]

    def mass(self, volume: float) -> typing.Optional[float]:
        """The mass in grams of 'volume' mm^3 of this material.

        None when the material does not state a density: a made-up mass is
        worse than no mass, because nothing downstream can tell it apart from a
        measured one.
        """
        density = self.density
        return None if density is None else volume * density

    def material_info(self) -> dict:
        """What this object is, as the '<label>: <value>' pairs 'pc info' prints.

        Named the way 'Software.software_info()' and 'Shape.shape_info()' are,
        and for the same reason: 'info' is the attribute a factory replaces, so
        the object's own half of the answer needs a name of its own.
        """
        info = {
            "Path": self.project_name,
            "Name": self.name,
        }
        if self.formal:
            info["Formal"] = self.formal
        if self.full:
            info["Full"] = self.full
        if self.desc:
            info["Desc"] = self.desc
        if self.density is not None:
            info["Density"] = "%g g/mm^3 (%g g/cm^3)" % (self.density, self.density_g_cm3)
        if self.tags:
            info["Tags"] = ", ".join(self.tags)
        if self.url:
            info["Url"] = self.url
        if self.errors:
            info["Errors"] = list(self.errors)
        return info

    def info(self) -> dict:
        return self.material_info()

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in self.name.lower() or keyword in str(self.config).lower()


def lookup(ctx, ref: str, quiet: bool = False):
    """The (package, material) a fully qualified reference points at.

    Both are None when the reference resolves to nothing. Reported here, once,
    rather than by each caller: a mass calculation and a manufacturing quote ask
    the same question, and a reference that does not resolve is the same mistake
    either way.

    'quiet' is for the callers that are not the ones to report it - a provider
    deciding whether it can make something out of what was asked for, which asks
    the same question moments before the caller that *will* report it.

    Shaped exactly like 'software.lookup()', because a caller resolving a
    reference should not have to learn a second way of doing it per kind.
    """
    package_name, name = resolve_resource_path("", ref)
    project = ctx.get_project(package_name) if ctx is not None else None
    if project is None:
        if not quiet:
            pc_logging.error("The material '%s' is not found: no such package" % ref)
        return None, None
    material = project.get_material(name, quiet=quiet)
    if material is None:
        # 'get_material' has already said why, unless it was asked not to.
        return project, None
    return project, material
