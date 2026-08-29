#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The 'software' a package ships beside its parts and assemblies.

A product is rarely hardware alone: the board in it runs a firmware image, the
controller boots a disk image, the host tool that talks to it is a binary. None
of that is geometry, so 'Software' is deliberately **not** a 'Shape': there is
nothing to tessellate, render, export or measure, and nothing here inherits the
machinery that exists for those. What software is, always, is a *file* -- and
the digital thread PartCAD maintains is only whole if that file is identified as
precisely as the parts around it are.

That is what this module is for. A 'Software' object knows where its file is
(the 'path' in the package, or what 'fileFrom' pulls it from), what it is for,
and -- for a file that is not kept in the package's own repository -- the hash
that says it is the right one. The bill of materials of an assembly lists it
beside the parts, with the revision of the package it came from, so that
"which firmware went into this unit" has the same kind of answer as "which
bracket went into this unit".
"""

import os
import typing

from . import logging as pc_logging
from . import telemetry
from .utils import normalize_resource_path, resolve_resource_path

# The kind of a software object. 'raw' is a file PartCAD hands over as it is:
# it is neither parsed nor transformed, and what to do with it is the reader's
# business. It is the default because it is the only thing that can be said
# about an arbitrary file without knowing the device it belongs to.
#
# Every type is a file, and that is not going to change: the types that come
# after 'raw' name the *procedure* the file goes through rather than a different
# kind of object. A 'uf2', a 'hex' or a 'dfu' image is still one file; what it
# adds is a specific firmware flashing procedure (which tool, which bootloader,
# which reset dance) that PartCAD can then carry out or at least describe. So a
# new type belongs beside this one, with the same 'path'/'fileFrom' plumbing
# underneath it, and never as a second way of pointing at a file.
DEFAULT_TYPE = "raw"


@telemetry.instrument()
class Software:
    """One software object of a package.

    'path' is the absolute path of the file on disk, whether the package keeps
    the file itself or 'fileFrom' pulls it in; it is where the file *will* be in
    the latter case, and it may not exist until the file is fetched.
    """

    name: str
    project_name: str
    desc: str
    kind: str = "software"
    config: dict[str, typing.Any]
    path: typing.Optional[str] = None
    url: typing.Optional[str] = None
    errors: list[str]

    def __init__(self, project_name: str, config: dict[str, typing.Any] = {}) -> None:
        self.project_name = project_name
        self.config = config
        self.name = config["name"]
        self.desc = config.get("desc", "")
        self.url = config.get("url", None)
        self.version = config.get("version", None)
        self.errors = []

        # Both filled in by the factory: the absolute path of the file, and the
        # coroutine that puts it there when 'fileFrom' has to fetch it. See
        # 'SoftwareFactory._create_software'.
        self.path = None
        self.prepare_async = None

    def error(self, msg: str) -> None:
        self.errors.append(msg)
        pc_logging.error("%s: %s: %s" % (self.project_name, self.name, msg))

    @property
    def type(self) -> str:
        return self.config.get("type", DEFAULT_TYPE)

    @property
    def is_fetched(self) -> bool:
        """Whether the file this object stands for is on disk right now."""
        return bool(self.path) and os.path.exists(self.path)

    def declared_hash(self) -> typing.Optional[str]:
        """The hash the declaration pins the file to, or None.

        A file the package does not carry (see 'fileFrom') is whatever the
        remote serves at the moment it is fetched, so a declaration that names
        no hash pins nothing at all. That is what 'lint/software.py' checks; this
        is where the value it checks is read from, so that the check and every
        consumer read the same field the same way.
        """
        value = self.config.get("hash")
        if value is None:
            return None
        return str(value).strip() or None

    def is_local_file(self) -> bool:
        """Whether the file lives in the package's own repository.

        True for a declaration that only points at a 'path'. False as soon as
        'fileFrom' is involved: the file is then fetched from somewhere else and
        is not part of what the package's revision identifies.
        """
        return "fileFrom" not in self.config

    def software_info(self) -> dict:
        """What this object is, as the '<label>: <value>' pairs 'pc info' prints.

        Named the way 'Shape.shape_info()' is, and for the same reason: the
        factory owns the 'info' attribute (it is what adds the package's URLs to
        this), so the object's own half of the answer needs a name of its own.
        """
        info = {
            "Path": self.project_name,
            "Type": self.type,
        }
        if self.desc:
            info["Desc"] = self.desc
        if self.version is not None:
            info["Version"] = str(self.version)
        if self.path is not None:
            info["File"] = self.path
        if self.url is not None:
            info["Url"] = self.url
        if self.config.get("fileFrom") is not None:
            info["FileFrom"] = self.config["fileFrom"]
        if self.config.get("fileUrl") is not None:
            info["FileUrl"] = self.config["fileUrl"]
        declared_hash = self.declared_hash()
        if declared_hash is not None:
            info["Hash"] = declared_hash
        if self.errors:
            info["Errors"] = list(self.errors)
        return info

    def info(self) -> dict:
        """The default, replaced by the factory that created this object."""
        return self.software_info()

    def matches(self, keyword: str) -> bool:
        if not keyword:
            return False
        keyword = keyword.lower()
        return keyword in self.name.lower() or keyword in str(self.config).lower()


# The key a resolved list of software references is stored under, beside the
# 'software' the package author wrote. Resolved once, by the factory that first
# sees the declaration, because that is the only place that knows which package
# authored it: an alias or an enrich hands its source's configuration on, and a
# reference in it means what it meant where it was written, not where it ended
# up being read.
RESOLVED_KEY = "software_resolved"


def declared_software_refs(project_name: str, config) -> list[str]:
    """The software an object declares, as fully qualified '<package>:<name>'.

    Accepts the one-entry short form ('software: firmware') as well as a list.
    Order is the author's, duplicates are dropped: the list says what the object
    ships with, and saying it twice does not make it two things.
    """
    if not isinstance(config, dict):
        return []
    refs = config.get("software")
    if not refs:
        return []
    if isinstance(refs, str):
        refs = [refs]
    resolved: list[str] = []
    for ref in refs:
        if not isinstance(ref, str) or not ref.strip():
            continue
        normalized = normalize_resource_path(project_name, ref.strip())
        if normalized not in resolved:
            resolved.append(normalized)
    return resolved


def resolved_software_refs(project_name: str, config) -> list[str]:
    """What an object ships with, preferring what its factory already resolved.

    The fallback covers the objects no factory produced - an assembly built in
    Python with 'add()' - and costs nothing for the rest.
    """
    if isinstance(config, dict):
        resolved = config.get(RESOLVED_KEY)
        if resolved:
            return list(resolved)
    return declared_software_refs(project_name, config)


def lookup(ctx, ref: str):
    """The (package, software) a fully qualified reference points at.

    Both are None when the reference resolves to nothing. Reported here, once,
    rather than by each caller: a bill of materials and a generated README ask
    the same question and a reference that does not resolve is the same mistake
    either way.
    """
    package_name, name = resolve_resource_path("", ref)
    project = ctx.get_project(package_name) if ctx is not None else None
    if project is None:
        pc_logging.error("The software '%s' is not found: no such package" % ref)
        return None, None
    software = project.get_software(name)
    if software is None:
        # 'get_software' has already said why.
        return project, None
    return project, software
