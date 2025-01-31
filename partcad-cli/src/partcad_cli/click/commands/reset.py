import os
import shutil
import rich_click as click
from partcad.logging import Action, Process, info
from partcad.user_config import user_config


@click.option(
    "--repo-only",
    is_flag=True,
    default=False,
    help="Remove the cached repositories only.",
)
@click.option(
    "--sandbox-only",
    is_flag=True,
    default=False,
    help="Remove the sandbox environments only.",
)
@click.option(
    "--cache-only",
    is_flag=True,
    default=False,
    help="Remove the filesystem caches only.",
)
@click.command(help="Reset all internal states maintained by PartCAD")
def cli(repo_only: bool, sandbox_only: bool, cache_only: bool) -> None:
    with Process("Reset", "global"):
        if repo_only or not (cache_only or sandbox_only):
            cached_import_types = ["git", "tar"]
            for import_type in cached_import_types:
                cache_dir = os.path.join(user_config.internal_state_dir, import_type)
                if os.path.exists(cache_dir):
                    with Action("Repos", import_type):
                        shutil.rmtree(cache_dir)
                        info(f"Removed cached {import_type} dependencies: '{cache_dir}'")

        if sandbox_only or not (repo_only or cache_only):
            sandbox_dir = os.path.join(user_config.internal_state_dir, "sandbox")
            if os.path.exists(sandbox_dir):
                for subdir in os.listdir(sandbox_dir):
                    with Action("Sandbox", subdir):
                        sandbox_subdir = os.path.join(sandbox_dir, subdir)
                        shutil.rmtree(sandbox_subdir)
                        info(f"Removed sandbox: '{subdir}'")

        if cache_only or not (repo_only or sandbox_only):
            cache_dir = os.path.join(user_config.internal_state_dir, "cache")
            if os.path.exists(cache_dir):
                for subdir in os.listdir(cache_dir):
                    with Action("cache", subdir):
                        cache_subdir = os.path.join(cache_dir, subdir)
                        shutil.rmtree(cache_subdir)
                        info(f"Removed cache: '{subdir}'")
