import rich_click as click
from partcad.logging import info, debug
from partcad.user_config import user_config


@click.command(help="Show the current user configuration")
@click.pass_obj
def cli(ctx) -> None:
    for key, value in vars(user_config).items():
        if not callable(value) and key[0] != "_":
            info(f"{key}: {value}")
    debug(f"File: {user_config.get_config_dir()}")
