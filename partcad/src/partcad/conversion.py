import os
from typing import List, Optional, Tuple
import partcad.logging as logging

def get_object_type(project, object_str: str) -> Tuple[List[str], List[str], List[str]]:
    """Return tuple of (parts, assemblies, sketches) for the object."""
    if object_str in project.parts:
        return [object_str], [], []
    elif object_str in project.assemblies:
        return [], [object_str], []
    elif object_str in project.sketches:
        return [], [], [object_str]
    else:
        raise ValueError(f"Object '{object_str}' not found in parts, assemblies, or sketches.")

def convert_object(project, object_str: str, target_format: str,
                   output_dir: Optional[str], in_place: bool) -> None:
    """Perform conversion and update configuration if needed."""
    # Determine object type.
    parts, assemblies, sketches = get_object_type(project, object_str)
    part_config = project.get_part_config(object_str)
    old_path = part_config.get("path")
    base_file_name = os.path.splitext(os.path.basename(old_path))[0] if old_path else object_str
    new_file_name = f"{base_file_name}.{target_format}"

    # Determine full output directory.
    if output_dir:
        full_output_dir = output_dir
    else:
        if old_path:
            full_output_dir = os.path.dirname(old_path) if os.path.isabs(old_path) \
                else os.path.join(project.path, os.path.dirname(old_path))
        else:
            full_output_dir = project.path

    # Construct the new file path.
    new_path = os.path.join(full_output_dir, new_file_name)

    with logging.Process("Convert", object_str):
        project.convert(
            sketches=sketches,
            interfaces=[],  # Reserved for future use.
            parts=parts,
            assemblies=assemblies,
            target_format=target_format,
            output_dir=new_path,
            in_place=in_place,
        )

    # Update configuration if requested.
    abs_project_path = os.path.abspath(project.path)
    abs_new_path = os.path.abspath(new_path)
    config_path = (os.path.relpath(abs_new_path, abs_project_path)
                   if abs_new_path.startswith(abs_project_path) else new_path)
    if in_place or output_dir:
        project.update_part_config(object_str, {"type": target_format, "path": config_path})
