import os
import shutil
import rich_click as click
from partcad.logging import Action, Process, info
from partcad.user_config import user_config


@click.command(help="Reset all internal states maintained by PartCAD")
def cli() -> None:
    with Process("Reset", "global"):
        cached_import_types = ["git", "tar"]
        for import_type in cached_import_types:
            cache_dir = os.path.join(user_config.internal_state_dir, import_type)
            if os.path.exists(cache_dir):
                with Action("Repos", import_type):
                    shutil.rmtree(cache_dir)
                    info(f"Removed cached {import_type} dependencies: '{cache_dir}'")

        runtime_dir = os.path.join(user_config.internal_state_dir, "runtime")
        if os.path.exists(runtime_dir):
            for subdir in os.listdir(runtime_dir):
                with Action("Runtime", subdir):
                    runtime_subdir = os.path.join(runtime_dir, subdir)
                    shutil.rmtree(runtime_subdir)
                    info(f"Removed runtime: '{subdir}'")

        cache_dir = os.path.join(user_config.internal_state_dir, "cache")
        if os.path.exists(cache_dir):
            for subdir in os.listdir(cache_dir):
                with Action("cache", subdir):
                    cache_subdir = os.path.join(cache_dir, subdir)
                    shutil.rmtree(cache_subdir)
                    info(f"Removed cache: '{subdir}'")
