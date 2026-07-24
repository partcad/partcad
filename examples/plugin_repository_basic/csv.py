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


def get(key):
    parts = load_parts()
    data = {
        "objects/part": parts,
        "deps": [],
        "meta": {"desc": "A CSV-backed example repository"},
    }
    for name, config in parts.items():
        data["objects/part/" + name] = config
    return data.get(key)


if __name__ == "get":
    output = {"result": get(request["key"])}  # noqa: F821 - 'request' is injected by the runtime
else:
    # Any other API (e.g. 'caps') has no data to return.
    output = {}
