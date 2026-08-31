#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""The throwaway package an ad-hoc command works inside.

`pc adhoc convert` and `pc adhoc render` both operate on a file that belongs to
no package: PartCAD writes a `partcad.yaml` in a temporary directory declaring
that one file as its only object, builds a context around it, produces one
output file, and deletes the directory again.

Everything specific to a verb lives in `convert.py` and `render.py`; what is
here is the part they share, so that a change to how the throwaway package is
built cannot mean one thing for a conversion and another for a projection.
"""

import asyncio
from pathlib import Path
import shutil
import tempfile

from .. import logging as pc_logging
from ..context import Context

# What a shape of each kind is called inside the throwaway package, and which
# section of its 'partcad.yaml' declares it. The names are not arbitrary: they
# are what the object is called, so they reach the user in an error message and
# (for a render) name the output file when the caller did not.
KINDS = {
    "part": ("parts", "input_part"),
    "sketch": ("sketches", "input_sketch"),
}


def generate_partcad_config(temp_dir: Path, input_type: str, temp_input_path: Path, kind: str = "part") -> None:
    """
    Generate a temporary partcad.yaml configuration for processing.

    Args:
        temp_dir (Path): Temporary directory path.
        input_type (str): Input file format type.
        temp_input_path (Path): Path to the copied input file.
        kind (str): Either "part" or "sketch" (default is "part")
    """
    section, name = KINDS[kind]

    # Doubling is how an apostrophe is escaped inside a YAML single-quoted
    # scalar. The path is the user's own -- '/home/me/part's.step' is a valid
    # file name -- and without this it closes the scalar early and the
    # throwaway package fails to parse before the input is ever read.
    quoted_path = str(temp_input_path).replace("'", "''")

    config = f"""
{section}:
  {name}:
    type: {input_type}
    path: '{quoted_path}'
    """
    config_path = temp_dir / "partcad.yaml"
    config_path.write_text(config.strip() + "\n", encoding="utf-8")


# Formats that describe an assembly rather than a single shape. An ad-hoc
# operation is a file-in, file-out one with a throwaway package around it; these
# need a real one. A URDF resolves its meshes against the package that holds them
# and produces a part per link, and an ASSY is nothing but references to parts of
# a package - neither means anything on its own.
PACKAGE_ONLY_TYPES = {
    "urdf": "a URDF names the meshes of its links and becomes a part per link",
    "assy": "an ASSY file is a set of references to the parts of a package",
}


def reject_package_only(input_type: str, output_type: str = None, verb: str = "convert", advice: str = None) -> None:
    """Refuse the formats that only mean something inside a package.

    'verb' and 'advice' are what the caller is doing and what it should do
    instead; the rest of the message is the same either way, because the reason
    is the same either way.
    """
    if advice is None:
        advice = "Use 'pc convert assembly' in a package instead."
    for role, part_type in (("from", input_type), ("to", output_type)):
        reason = PACKAGE_ONLY_TYPES.get((part_type or "").lower())
        if reason is not None:
            raise ValueError(
                "Cannot %s %s '%s' ad-hoc: %s, so it only means anything inside a package. %s"
                % (verb, role, part_type, reason, advice)
            )


def write_output_file(
    input_filename: str,
    input_type: str,
    output_filename: str,
    output_type: str,
    kind: str = "part",
    verb: str = "Convert",
    **options,
) -> None:
    """Produce one output file from a CAD file that belongs to no package.

    Args:
        input_filename: Path to the input file.
        input_type: Format of the input file.
        output_filename: Path to write.
        output_type: The file type to write - a part or sketch format for a
            conversion, a 2D projection for a render.
        kind: "part" or "sketch", which decides how the input is declared.
        verb: What is being done, for the progress label and the error message.
        options: Export parameters handed to the implementation, overriding what
            it would otherwise default to. This is where a render's viewport
            arrives; a conversion passes none.

    Raises:
        RuntimeError: the input could not be loaded, or the output not written.
            The cause is in the message and not only in '__cause__', because
            this is what the CLI prints.
    """
    _, object_name = KINDS[kind]
    input_path = Path(input_filename).resolve()
    temp_dir = Path(tempfile.mkdtemp())

    try:
        generate_partcad_config(temp_dir, input_type, input_path, kind=kind)

        ctx = Context(root_path=temp_dir, search_root=False)
        with pc_logging.Process(verb, "adhoc" if kind == "part" else "adhoc-sketch"):
            project = ctx.get_project("//")
            obj = project.get_part(object_name) if kind == "part" else project.get_sketch(object_name)
            if not obj:
                raise RuntimeError(f"Failed to load the input {kind}: no {kind} returned")

            shape = asyncio.run(obj.get_wrapped(ctx))
            # Errors first: when the factory failed - a missing module, a
            # sandbox that would not install - that is the reason there is no
            # shape, and it is the one worth reporting. "No shape returned" is
            # what is left to say when nothing was recorded.
            if obj.errors:
                raise RuntimeError(f"Failed to load the input {kind}: {obj.errors}")
            if not shape:
                raise RuntimeError(f"Failed to load the input {kind}: no shape returned")

            if kind == "part":
                pc_logging.info(f"Loaded input part: {input_path}")
                pc_logging.info(f"Shape: {type(shape)}")
            else:
                pc_logging.debug(f"Loaded input sketch: {input_path}")

            obj.render(
                ctx=ctx,
                format_name=output_type,
                project=project,
                filepath=output_filename,
                **options,
            )

    except Exception as e:
        subject = "" if kind == "part" else " sketch"
        raise RuntimeError(f"Failed to {verb.lower()}{subject}: {e}") from e
    finally:
        shutil.rmtree(temp_dir)
