#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The package/object hierarchy the explorer shows.

The service reports a package's contents through the ``items`` notification (one
level at a time, the same call ``pc list all -r`` walks recursively and the VS
Code explorer expands lazily). This module turns that payload into plain objects
and orders them the way the other PartCAD front ends do: packages first, then
assemblies, parts, interfaces and sketches, with aliases after their originals.
"""

from typing import Optional

KIND_PACKAGE = "package"
KIND_ASSEMBLY = "assembly"
KIND_PART = "part"
KIND_INTERFACE = "interface"
KIND_SKETCH = "sketch"

# The kinds this addon can turn into geometry. Sketches and interfaces are shown
# for orientation but have no STEP to import.
IMPORTABLE_KINDS = (KIND_PART, KIND_ASSEMBLY)

# The `items` payload key each kind arrives under, and the order the explorer
# lists them in.
_SECTIONS = (
    ("packages", KIND_PACKAGE),
    ("assemblies", KIND_ASSEMBLY),
    ("parts", KIND_PART),
    ("interfaces", KIND_INTERFACE),
    ("sketches", KIND_SKETCH),
)


class Item:
    """One node of the explorer tree: a package or an object inside one."""

    def __init__(self, kind: str, name: str, package: str, config: Optional[dict] = None):
        self.kind = kind
        self.name = name
        # For a package this is its *parent*; for an object, the package that
        # defines it. Either way it is what `<package>:<name>` needs.
        self.package = package
        self.config = config or {}

    @property
    def desc(self) -> str:
        return self.config.get("desc") or ""

    @property
    def type(self) -> str:
        return self.config.get("type") or ""

    @property
    def item_path(self) -> Optional[str]:
        return self.config.get("item_path")

    @property
    def parameters(self) -> dict:
        return self.config.get("parameters") or {}

    @property
    def is_alias(self) -> bool:
        return self.type == "alias"

    @property
    def is_importable(self) -> bool:
        return self.kind in IMPORTABLE_KINDS

    @property
    def label(self) -> str:
        """The short name to show. Child packages are reported by full path."""
        if self.kind == KIND_PACKAGE:
            return self.name.rstrip("/").rsplit("/", 1)[-1] or self.name
        return self.name

    @property
    def qualified_name(self) -> str:
        """``<package>:<name>``, how PartCAD addresses an object everywhere."""
        if self.kind == KIND_PACKAGE:
            return self.name
        return "%s:%s" % (self.package, self.name)

    def __repr__(self) -> str:  # pragma: no cover - debugging aid
        return "Item(%s, %s)" % (self.kind, self.qualified_name)


class PackageContents:
    """Everything one package directly contains, in display order."""

    def __init__(self, name: str, items: list):
        self.name = name
        self.items = items

    def of_kind(self, kind: str) -> list:
        return [item for item in self.items if item.kind == kind]

    def __len__(self) -> int:
        return len(self.items)

    def __iter__(self):
        return iter(self.items)


def _sort_key(item: Item):
    # Aliases duplicate an object that is listed elsewhere, so they go last --
    # the same ordering the VS Code explorer applies.
    return (1 if item.is_alias else 0, item.name.lower(), item.name)


def parse_items(payload: dict) -> PackageContents:
    """Turn one ``items`` notification into a :class:`PackageContents`."""
    payload = payload or {}
    package = payload.get("name") or "//"
    items = []
    for key, kind in _SECTIONS:
        section = payload.get(key) or []
        configs = [config for config in section if isinstance(config, dict)]
        entries = [Item(kind, config.get("name") or "", package, config) for config in configs]
        items.extend(sorted((entry for entry in entries if entry.name), key=_sort_key))
    return PackageContents(package, items)
