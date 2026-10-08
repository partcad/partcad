#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""What a file is checked with, worked out from the package configurations around it.

An ASSY file and a `partcad.yaml` are Jinja2 templates, and `assy_lint` checks
what they render to. That takes the values PartCAD renders them with, and for
an ASSY file those are not in the file: they are the parameters of whatever
declares it. Two more things about a file are not in it either -- whether an
ASSY file is read as an assembly or as a scene (its *flavor*), and whether what
it describes is marked manufacturable, which decides whether the rules for
things that are to be made apply (see 'assy_lint.check_manufacturable_*').

All three are answered here, from the `partcad.yaml` files from the file's own
directory upwards, each rendered the way PartCAD renders it. That is text, not a
loaded context, and that is deliberate twice over. A client checks the file an
editor has open, often unsaved and often in a package that does not load
*because* of it, and must not import the CAD kernel to do it. And the daemon,
which does have the package graph, asks the same question here rather than of
the graph, so that an editor and `pc lint` cannot answer it differently.

What that costs is precision at the edges, and every edge leans the way that
underlines less: a package that is not in a directory above the file it imports
is not seen (so neither is what it marks manufacturable), a declaration whose
`path:` only resolves with parameters is not matched, and a file nothing
declares is checked masked rather than rendered (see 'assy_lint.validate_source').
"""

import copy
import os

import yaml

from . import __version__, assy_lint, config_template, template_render
from .parameters import coerce_parameter_value, normalize_parameters

# How far up from the file the search for a package declaring it goes. A
# package's own directory is where it is normally declared; an ancestor package
# can declare it too, with a `path:` that reaches down. Bounded because this
# runs on every keystroke in an editor, and because walking to the filesystem
# root would start reading other people's packages.
MAX_PACKAGE_DEPTH = 8

CONFIG_FILENAME = "partcad.yaml"

# The sections that may point at an ASSY file, and the flavor each one makes it.
SECTIONS = {
    "assemblies": assy_lint.FLAVOR_ASSEMBLY,
    "scenes": assy_lint.FLAVOR_SCENE,
}

# The object types within those sections that name an ASSY file. A scene of
# type 'world' points at a Gazebo world, not at an ASSY, and says nothing about
# how any '.assy' file should be read.
ASSY_TYPES = ("assy",)


class FileContext:
    """Everything a file is checked with besides its own text and schema.

    ``flavor`` -- for an ASSY file, `FLAVOR_ASSEMBLY` or `FLAVOR_SCENE`; None
    for a `partcad.yaml`. ``renders`` -- the `assy_lint.Render` for each
    declaration of an ASSY file, or the one for a `partcad.yaml`; empty when
    nothing declares the file. ``manufacturable`` -- whether an ASSY file is the
    assembly of something marked manufacturable. ``inherited_manufacturable``
    -- for a `partcad.yaml`, what the packages above it mark: True, False, or
    None for nothing.
    """

    def __init__(self, flavor=None, renders=(), manufacturable=False, inherited_manufacturable=None):
        self.flavor = flavor
        self.renders = list(renders)
        self.manufacturable = manufacturable
        self.inherited_manufacturable = inherited_manufacturable

    def check(self, text: str, schema: dict) -> list:
        """Check ``text`` against ``schema`` with everything this context knows."""
        return assy_lint.validate_source(
            text,
            schema,
            renders=self.renders,
            manufacturable=self.manufacturable,
            inherited_manufacturable=self.inherited_manufacturable,
        )


def describe(path: str, package_name: str = "", include_paths=(), parameter_overrides=None) -> FileContext:
    """Work out what ``path`` is checked with. See the module docstring.

    ``package_name`` is the name a `partcad.yaml` is rendered with, which only
    the daemon knows; a client renders it with none. ``include_paths`` are
    directories to include from besides the ones the packages declare -- for
    what a package this cannot see declares (the editor's
    'partcad.lint.includePaths'). ``parameter_overrides`` replace declared
    defaults, as PartCAD's own do: object name -> {parameter: value}, the shape
    '--extra-param' and the 'parameters:' of '~/.partcad/config.yaml' fill in
    (see '_overrides_for' for how an object is named). Never raises: this runs on
    every keystroke, against whatever the packages around the file say, and
    knowing nothing about them is a reason to check the file masked, not a
    reason for the check to fail.
    """
    try:
        return _describe(os.path.abspath(path), package_name, list(include_paths or ()), parameter_overrides)
    except Exception:  # pylint: disable=broad-except
        return FileContext(
            flavor=assy_lint.FLAVOR_ASSEMBLY if assy_lint.is_assy_file(path) else None,
        )


def _describe(target: str, package_name: str, include_paths: list, parameter_overrides) -> FileContext:
    directory = os.path.dirname(target)
    if assy_lint.schema_name_for_file(target) == assy_lint.PARTCAD_SCHEMA:
        above = _packages_above(os.path.dirname(directory), include_paths)
        return FileContext(
            renders=[
                assy_lint.Render(
                    config_template.render_context(package_name, __version__),
                    _search_path(directory, above) + include_paths,
                )
            ],
            inherited_manufacturable=_marked(above),
        )
    if not assy_lint.is_assy_file(target):
        return FileContext()

    configs = _packages_above(directory, include_paths)
    flavor = assy_lint.FLAVOR_ASSEMBLY
    declarations = {assy_lint.FLAVOR_ASSEMBLY: [], assy_lint.FLAVOR_SCENE: []}
    for depth, (package_dir, config) in enumerate(configs):
        for section, section_flavor in SECTIONS.items():
            for name, declaration in _declarations(config, section):
                if _declared_path(package_dir, name, declaration) == target:
                    declarations[section_flavor].append((name, declaration, configs[depth:]))
    # One assembly is enough: the file has to satisfy the full schema for that
    # assembly to be readable, whatever else also points at it. Unknown leans
    # the same way, because reading an assembly as a scene puts a false error
    # on correct code.
    if not declarations[assy_lint.FLAVOR_ASSEMBLY] and declarations[assy_lint.FLAVOR_SCENE]:
        flavor = assy_lint.FLAVOR_SCENE
    chosen = declarations[flavor]

    renders = []
    manufacturable = False
    for name, declaration, configs_from_its_package in chosen:
        overrides = _overrides_for(name, package_name, parameter_overrides)
        renders.append(
            assy_lint.Render(_template_params(name, declaration, overrides), [directory] + include_paths, label=name)
        )
        mark = declaration.get("manufacturable")
        if mark is None and flavor == assy_lint.FLAVOR_ASSEMBLY:
            # A scene is not a product to be made unless it says so itself; an
            # assembly is what its package marks it (see 'partcad.scene_config').
            mark = _marked(configs_from_its_package)
        manufacturable = manufacturable or (mark is True and _held_to_connectivity(declaration))
    return FileContext(flavor=flavor, renders=renders, manufacturable=manufacturable)


def _held_to_connectivity(declaration: dict) -> bool:
    """Whether 'pc test' holds this declaration to its 'connectivity' rules at all.

    'partcad.test.connectivity' stops before its manufacturable rule for an
    assembly that says 'requireAnchored: false', and does not run for one that
    says 'skip: true'; the editor says no more than the test would.
    """
    connectivity = declaration.get("connectivity")
    if not isinstance(connectivity, dict):
        return True
    return connectivity.get("requireAnchored", True) is not False and connectivity.get("skip") is not True


def _template_params(name: str, declaration: dict, overrides: dict = None) -> dict:
    """What PartCAD renders a declared file with: see 'AssemblyFactoryFile.template_params'.

    Each declared default, replaced by ``overrides`` where it names the
    parameter -- read as the type the parameter declares, as PartCAD reads it
    ('partcad.config.apply_user_parameter_overrides'), since a value from
    '--extra-param' or an editor setting is text. One that will not read as its
    type is left out, as PartCAD leaves it out, and the default stands.
    """
    declared = copy.deepcopy(declaration.get("parameters"))
    params = {}
    if isinstance(declared, dict):
        declared = normalize_parameters(declared)
        for param_name, param in declared.items():
            if isinstance(param, dict):
                params["param_" + str(param_name)] = param.get("default")
        for param_name, value in (overrides or {}).items():
            param = declared.get(param_name)
            if not isinstance(param, dict):
                # Not a parameter of this object: PartCAD ignores it too.
                continue
            try:
                value = coerce_parameter_value(param.get("type"), value, str(param_name), name)
            except (ArithmeticError, TypeError, ValueError):
                continue
            params["param_" + str(param_name)] = value
    params["name"] = name
    return params


def _overrides_for(name: str, package_name: str, parameter_overrides) -> dict:
    """The parameter values ``parameter_overrides`` give the object called ``name``.

    PartCAD names an object by its package and its name ('//pub/x:desk'), and
    where the package is known so is the match -- exactly, as PartCAD makes it.
    A client checking one file does not know the package's name, so an
    override names the object with it, with only ':desk', or as just 'desk'.
    """
    found = {}
    if not isinstance(parameter_overrides, dict):
        return found
    for object_name, values in parameter_overrides.items():
        if not isinstance(values, dict):
            continue
        object_name = str(object_name)
        if package_name:
            wanted = object_name == "%s:%s" % (package_name, name)
        else:
            wanted = object_name == name or object_name.endswith(":" + name)
        if wanted:
            found.update(values)
    return found


def _declarations(config: dict, section: str):
    declarations = config.get(section)
    if not isinstance(declarations, dict):
        return
    for name, declaration in declarations.items():
        if isinstance(declaration, dict) and declaration.get("type") in ASSY_TYPES:
            yield str(name), declaration


def _declared_path(package_dir: str, name: str, declaration: dict):
    declared = declaration.get("path")
    if declared is None:
        declared = "%s.assy" % name
    if not isinstance(declared, str) or not declared:
        return None
    return os.path.abspath(os.path.join(package_dir, declared))


def _marked(configs) -> bool:
    """What the nearest of ``configs`` that says anything marks its objects, or None."""
    for _, config in configs:
        mark = config.get("manufacturable")
        if isinstance(mark, bool):
            return mark
    return None


def _packages_above(directory: str, include_paths=()) -> list:
    """(directory, rendered configuration) of every package from ``directory`` upwards, nearest first.

    Read from the top down, because a package's own rendering can depend on the
    one above it: a dependency declared with 'includePaths' is rendered with
    those directories to include from (see 'ProjectLocal').
    """
    found = []
    for _ in range(MAX_PACKAGE_DEPTH):
        config_path = os.path.join(directory, CONFIG_FILENAME)
        if os.path.isfile(config_path):
            found.append(directory)
        parent = os.path.dirname(directory)
        if parent == directory:
            break
        directory = parent
    loaded = []
    for package_dir in reversed(found):
        config = _load(
            os.path.join(package_dir, CONFIG_FILENAME), _search_path(package_dir, loaded) + list(include_paths)
        )
        if isinstance(config, dict):
            loaded.insert(0, (package_dir, config))
    return loaded


def _search_path(package_dir: str, above) -> list:
    """Where a package's `partcad.yaml` includes from: its own directory, and what the packages above add.

    A dependency declared with 'includePaths' is rendered with each of them,
    relative to the dependency's own directory, after the directory itself
    (see 'ProjectFactory' and 'ProjectLocal').
    """
    search_path = [package_dir]
    target = os.path.abspath(package_dir)
    for parent_dir, config in above:
        dependencies = config.get("dependencies")
        if not isinstance(dependencies, dict):
            continue
        for dependency in dependencies.values():
            if not isinstance(dependency, dict) or not isinstance(dependency.get("path"), str):
                continue
            declared = os.path.abspath(os.path.join(parent_dir, dependency["path"]))
            if declared not in (target, os.path.join(target, CONFIG_FILENAME)):
                continue
            include_paths = dependency.get("includePaths")
            if isinstance(include_paths, str):
                include_paths = [include_paths]
            for include_path in include_paths if isinstance(include_paths, list) else []:
                if isinstance(include_path, str):
                    search_path.append(os.path.join(package_dir, include_path))
    return search_path


def _load(config_path: str, search_path):
    """A `partcad.yaml` as PartCAD reads it: rendered, then parsed. None if it cannot be read."""
    try:
        with open(config_path, "r", encoding="utf-8") as file:
            text = file.read()
    except (OSError, UnicodeDecodeError):
        return None
    try:
        rendered = template_render.render_plain(text, config_template.render_context("", __version__), search_path)
    except template_render.RenderError:
        # Not knowing what it renders to is not a reason to know nothing: most
        # of a package that will not render is still plain YAML.
        rendered = text
    try:
        return yaml.safe_load(rendered)
    except Exception:  # pylint: disable=broad-except
        # Not only 'yaml.YAMLError': a date that is not one raises 'ValueError',
        # and nesting deep enough 'RecursionError'.
        return None
