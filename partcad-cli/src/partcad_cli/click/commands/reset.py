import os
import shutil
import rich_click as click
from partcad.logging import Process, info
from partcad.context import Context
from partcad.user_config import user_config


@click.command(help="Reset all internal states maintained by PartCAD")
@click.pass_obj
def cli(ctx: Context) -> None:
    with Process("Reset", "this"):
        for _, package_info in ctx.config_obj.get("import", {}).items():
            import_type = package_info["type"]
            cache_dir = os.path.join(user_config.internal_state_dir, import_type)
            if os.path.exists(cache_dir):
                info(f"Removing cached {import_type} imports: '{cache_dir}'")
                shutil.rmtree(cache_dir)

        runtime_dir = os.path.join(user_config.internal_state_dir, "runtime")
        if os.path.exists(runtime_dir):
            info(f"Removing runtime: '{runtime_dir}'")
            shutil.rmtree(runtime_dir)
