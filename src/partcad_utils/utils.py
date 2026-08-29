#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-20
#
# Licensed under Apache License, Version 2.0.

import os
import re
import sys
from types import ModuleType, FunctionType
from gc import get_referents

from urllib.parse import unquote, urlparse

from . import telemetry
from . import logging as pc_logging

# What counts as a URL rather than a path, wherever PartCAD has to tell the two
# apart. Deliberately just the two schemes 'fileFrom: url' can actually fetch:
# anything else is far more likely to be a path that happens to contain a colon
# (a Windows drive letter, an scp-style git remote) than a source PartCAD could
# read.
#
# Here rather than beside the code that fetches, because the thin CLI commands
# have to make the same judgement before handing an argument to the daemon, and
# they must not import the heavy 'partcad' package to do it (see "Command
# boundary" in src/partcad_cli/AGENTS.md).
URL_SCHEMES = ("http", "https")


def looks_like_url(value) -> bool:
    """Whether this argument names a URL to fetch rather than a file on disk."""
    if not isinstance(value, str):
        return False
    try:
        return urlparse(value).scheme.lower() in URL_SCHEMES
    except ValueError:
        return False


def filename_from_url(url: str, fallback: str = "download") -> str:
    """The file name a URL would sensibly be saved as.

    The last segment of the path, percent-decoding undone so that a URL ending
    in '%20' does not become a file name with a literal one in it. A URL with no
    path segment at all (a bare host, a directory) has no name to offer, and the
    caller's fallback is used instead - as it is for anything that could climb
    out of the directory it is joined onto.
    """
    name = os.path.basename(unquote(urlparse(url).path or "")).strip()
    if not name or name in (".", "..") or "/" in name or "\\" in name:
        return fallback
    return name


# Custom objects know their class.
# Function objects seem to know way too much, including modules.
# Exclude modules as well.
BLACKLIST = type, ModuleType, FunctionType


def get_child_project_path(parent_path, child_name):
    if parent_path.endswith("/"):
        result = parent_path + child_name
    else:
        result = parent_path + "/" + child_name

    result = re.sub(r"/[^/]*/\.\.", "", result)
    if result != "//":
        result = re.sub(r"/$", "", result)
    return result


def parse_parameterized_name(name: str) -> tuple:
    """Split '<name>;<param>=<value>,...' into the name and the parameters.

    The one spelling PartCAD has for an instance of an object with particular
    parameter values, and the one place that knows how to read it. The values
    come back as the strings they were written as; what type each of them is
    belongs to the parameter the object declares (see 'Project.get_object').
    """
    base, _, suffix = name.partition(";")
    parameters = {}
    for pair in suffix.split(",") if suffix else []:
        parameter, _, value = pair.partition("=")
        parameters[parameter] = value
    return base, parameters


def format_parameterized_name(base: str, parameters: dict) -> str:
    """The name of the instance of 'base' with these parameter values.

    Sorted, so that the same parameters always spell the same name and so ask
    for the same instance. 'base' may already carry parameters of its own, and
    the ones given here take precedence over those: they come from whoever is
    referring to it, which is the outer of the two.
    """
    base, inherited = parse_parameterized_name(base)
    inherited.update(parameters)
    if not inherited:
        return base
    return base + ";" + ",".join("%s=%s" % (name, inherited[name]) for name in sorted(inherited))


@telemetry.start_as_current_span("resolve_resource_path")
def resolve_resource_path(current_project_name, pattern: str):
    if not ":" in pattern:
        pattern = ":" + pattern
    project_pattern, item_pattern = pattern.split(":")
    if project_pattern == "":
        project_pattern = current_project_name

    # For backward compatibility '/' -> '//'
    if re.match(r"^/[^/]", project_pattern):
        pc_logging.warning(f"{project_pattern}: using '/' as the root package path is deprecated. Use '//' instead.")
        project_pattern = "/" + project_pattern
    project_pattern = project_pattern.replace("...", "*")
    if not project_pattern.startswith("//"):
        if current_project_name.endswith("/"):
            project_pattern = current_project_name + project_pattern
        else:
            project_pattern = current_project_name + "/" + project_pattern
    project_pattern = re.sub(r"/[^/]*/\.\.", "", project_pattern)
    item_pattern = item_pattern.replace("...", "*")

    return project_pattern, item_pattern


@telemetry.start_as_current_span("normalize_resource_path")
def normalize_resource_path(current_project_name, pattern: str):
    project_pattern, item_pattern = resolve_resource_path(current_project_name, pattern)
    return f"{project_pattern}:{item_pattern}"


def total_size(obj, verbose=False):
    """sum size of object & members."""
    if isinstance(obj, BLACKLIST):
        raise TypeError("getsize() does not take argument of type: " + str(type(obj)))
    seen_ids = set()
    size = 0
    objects = [obj]
    while objects:
        need_referents = []
        for obj in objects:
            if not isinstance(obj, BLACKLIST) and id(obj) not in seen_ids:
                seen_ids.add(id(obj))
                s = sys.getsizeof(obj)
                if verbose:
                    print(s, type(obj), repr(obj), file=sys.stderr)
                size += s
                need_referents.append(obj)
        objects = get_referents(*need_referents)
    return size


def is_editable_install(module):
    """
    Checks if a Python module is loaded from an editable install.

    Args:
        module: The Python module object.

    Returns:
        True if the module is from an editable install, False otherwise.
    """
    # A PyInstaller bundle carries no site-packages at all, so the heuristics
    # below would call every frozen module editable. It is the opposite: the
    # code was frozen at build time and cannot be edited in place.
    if getattr(sys, "frozen", False):
        return False

    if not hasattr(module, "__file__"):
        return False  # Built-in or dynamically generated modules

    module_file = getattr(module, "__file__")
    if module_file is None:
        return False  # e.g. from zip files without file system access

    # Check for symlinks, which are common in editable installs.
    if os.path.islink(module_file):
        return True

    # Check if the path is outside of the site-packages or similar directories.
    site_packages_dirs = [p for p in sys.path if "site-packages" in p]

    if not site_packages_dirs:
        return True  # If site-packages is not in sys.path, it is likely editable.

    for site_packages_dir in site_packages_dirs:
        if os.path.abspath(module_file).startswith(os.path.abspath(site_packages_dir)):
            return False  # Standard install

    return True  # Editable install
