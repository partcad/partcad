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

from . import telemetry
from . import logging as pc_logging

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
