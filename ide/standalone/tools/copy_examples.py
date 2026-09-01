#
# PartCAD, 2026
#
# Author: PartCAD (support@partcad.org)
#
# Licensed under Apache License, Version 2.0.
#

"""
Put the examples the IDE's welcome window offers inside the bootstrap extension.

They are not a second copy of anything: they are the packages under `examples/`
in this repository, which CI renders and compares byte for byte, so what the IDE
hands a user is what the project publishes. `../bootstrap/examples.json` says
which of them, what to call each one in the list the user picks from, and which
file to open.

An example is a package, and a package may reference a sibling of its own --
`../produce_part_cadquery_primitive`, in an assembly that places parts from it.
Copied out of `examples/` on its own, that reference points at nothing, and the
Explorer shows a package that will not load. So the manifest declares what each
example brings with it, this checks that the declaration is what the files
actually reference, and the extension copies a whole entry and its `requires`
together into one directory.

Run by `../build.sh` into the staging copy of the extension; the repository's own
`bootstrap/` never has an `examples/` directory in it.
"""

import argparse
import json
import pathlib
import re
import shutil
import sys

# Where a package names another one relative to itself. Read from the files that
# hold package references -- the package configuration and the assemblies -- and
# not from sources or documents, where `../` is a path in somebody's script or a
# link in a README.
REFERENCE_FILES = ("partcad.yaml", "*.assy")
SIBLING_REFERENCE = re.compile(r"\.\./([A-Za-z0-9._-]+)")

PACKAGE_CONFIGURATION = "partcad.yaml"

REQUIRED_KEYS = ("package", "label", "detail", "open")
OPTIONAL_KEYS = ("requires", "documentation")


class ManifestError(Exception):
    """The manifest and the examples in the repository do not agree."""


def load_manifest(path: pathlib.Path) -> list[dict]:
    """The examples the welcome window offers, in the order it offers them."""
    document = json.loads(path.read_text(encoding="utf-8"))
    examples = document.get("examples")
    if not examples:
        raise ManifestError(f"{path} lists no examples")

    seen = set()
    for example in examples:
        missing = [key for key in REQUIRED_KEYS if not example.get(key)]
        if missing:
            raise ManifestError(f"{path}: an entry is missing {', '.join(missing)}")
        unknown = set(example) - set(REQUIRED_KEYS) - set(OPTIONAL_KEYS)
        if unknown:
            raise ManifestError(f"{path}: {example['package']} has unknown key(s): {', '.join(sorted(unknown))}")
        if example["package"] in seen:
            raise ManifestError(f"{path}: {example['package']} is listed twice")
        seen.add(example["package"])
    return examples


def sibling_references(directory: pathlib.Path) -> set[str]:
    """The packages beside this one that its configuration and assemblies name."""
    found = set()
    for pattern in REFERENCE_FILES:
        for path in sorted(directory.glob(pattern)):
            found.update(SIBLING_REFERENCE.findall(path.read_text(encoding="utf-8")))
    # A package that refers to itself by path (`../<its own name>:part`, which
    # an alias or an enrich does) is asking for a sibling that is itself, and
    # still is one after the copy.
    return found - {directory.name}


def packages_to_copy(examples: list[dict]) -> dict[str, list[str]]:
    """Map each example to the packages that go with it, itself first."""
    return {example["package"]: [example["package"], *example.get("requires", [])] for example in examples}


def validate(examples: list[dict], examples_root: pathlib.Path) -> None:
    """Fail on anything that produces a welcome window offering a broken package."""
    for example in examples:
        directory = examples_root / example["package"]
        if not (directory / PACKAGE_CONFIGURATION).is_file():
            raise ManifestError(f"{directory} is not a PartCAD package (no {PACKAGE_CONFIGURATION})")
        if not (directory / example["open"]).is_file():
            raise ManifestError(f"{example['package']} has no {example['open']} to open")

    for example in examples:
        directory = examples_root / example["package"]
        required = list(example.get("requires", []))
        for name in required:
            if not (examples_root / name / PACKAGE_CONFIGURATION).is_file():
                raise ManifestError(f"{example['package']} requires {name}, which is not a package in {examples_root}")

        # Every sibling an example names has to travel with it, and the ones it
        # brings have to be complete themselves -- an assembly's parts are in a
        # package that may reference a third.
        pending = [example["package"], *required]
        declared = set(required)
        while pending:
            name = pending.pop()
            for reference in sibling_references(examples_root / name):
                if reference not in declared:
                    raise ManifestError(
                        f"{example['package']} would be copied without {reference}, which {name} references: "
                        f"add it to 'requires' in the manifest"
                    )
    return None


def copy(examples: list[dict], examples_root: pathlib.Path, output: pathlib.Path) -> list[str]:
    """Copy every package the manifest needs into `output`. Returns their names."""
    needed = sorted({name for names in packages_to_copy(examples).values() for name in names})
    if output.exists():
        shutil.rmtree(output)
    output.mkdir(parents=True)
    for name in needed:
        shutil.copytree(examples_root / name, output / name)
    return needed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--repo-root", type=pathlib.Path, required=True, help="the repository holding 'examples/'")
    parser.add_argument("--manifest", type=pathlib.Path, required=True, help="the extension's examples.json")
    parser.add_argument("--output", type=pathlib.Path, required=True, help="where to put the copies")
    parser.add_argument("--check", action="store_true", help="validate the manifest and copy nothing")
    args = parser.parse_args(argv)

    examples_root = args.repo_root / "examples"
    try:
        examples = load_manifest(args.manifest)
        validate(examples, examples_root)
    except (ManifestError, OSError, ValueError) as error:
        print(f"error: {error}", file=sys.stderr)
        return 1

    if args.check:
        print(f"{len(examples)} example(s) in {args.manifest}, all present in {examples_root}")
        return 0

    copied = copy(examples, examples_root, args.output)
    for example in examples:
        extra = [name for name in example.get("requires", [])]
        with_them = f" (with {', '.join(extra)})" if extra else ""
        print(f"  example  {example['label']}: {example['package']}{with_them}")
    print(f"Copied {len(copied)} package(s) into {args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
