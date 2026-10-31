#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#
# A 'basic' repository plugin backed by a local CSV file.
#
# PartCAD runs this script for every data request, with the generic key in
# 'request["key"]' and '__name__' set to the API ("get"); it returns
# '{"result": <value>}'. See the "Repositories" section of the documentation for
# the key conventions.
#
# NOTE: the file is named 'csv.py' (after the repository), so it must not
# 'import csv' - that would import this file, not the standard library. The
# small comma-separated format is parsed by hand instead.

import base64
import os
import urllib.parse


def load_parts():
    """Read the CSV into the part catalog: {name: {config}}."""
    parts = {}
    filename = request["parameters"].get("filename")  # noqa: F821 - injected by the runtime
    try:
        with open(filename) as csv_file:
            rows = [line.rstrip("\n") for line in csv_file if line.strip()]
    except (FileNotFoundError, TypeError):
        return parts
    if not rows:
        return parts
    header = rows[0].split(",")
    for row in rows[1:]:
        fields = dict(zip(header, row.split(",")))
        parts[fields["name"]] = {
            "type": fields["type"],
            "path": fields["filename"],
            "desc": fields.get("desc", ""),
        }
    return parts


def get_file(rel_path):
    """Return the base64 content of a file the catalog points at.

    The paths in the CSV are relative to this plugin, so resolve them relative
    to this script's directory and hand the bytes back for PartCAD to
    materialize into the package's cache directory.
    """
    base = os.path.dirname(os.path.abspath(__file__))
    try:
        with open(os.path.join(base, rel_path), "rb") as f:
            return base64.b64encode(f.read()).decode()
    except (FileNotFoundError, OSError):
        return None


def search(parts, query):
    """The parts whose name or description holds every word of the query, as {name: config}.

    'query' is the query string of a 'search/part?q=<text>&limit=<n>' key. A
    repository with a catalog nobody can list answers this from the catalog's
    own search instead; this one has its parts at hand, so it matches them.
    """
    fields = urllib.parse.parse_qs(query)
    words = " ".join(fields.get("q", [""])).lower().split()
    limit = int(fields.get("limit", ["0"])[0] or 0)
    found = {}
    for name, config in parts.items():
        text = (name + " " + config.get("desc", "")).lower()
        if all(word in text for word in words):
            found[name] = config
            if limit and len(found) >= limit:
                break
    return found


def get(key):
    if key.startswith("files/"):
        return get_file(key[len("files/") :])
    parts = load_parts()
    if key.startswith("search/part?"):
        return search(parts, key.partition("?")[2])
    data = {
        "objects/part": parts,
        "deps": [],
        # 'searchKinds' says the repository answers 'search/part?...' itself,
        # so 'pc search parts' asks it rather than matching what it lists.
        "meta": {"desc": "A CSV-backed example repository", "searchKinds": ["part"]},
    }
    for name, config in parts.items():
        data["objects/part/" + name] = config
    return data.get(key)


if __name__ == "get":
    output = {"result": get(request["key"])}  # noqa: F821 - 'request' is injected by the runtime
else:
    # Any other API (e.g. 'caps') has no data to return.
    output = {}
