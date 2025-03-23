#
# OpenVMP, 2025
#
# Licensed under Apache License, Version 2.0.
#

import rich_click as click
import importlib
import os

import partcad as pc


class Loader(click.RichGroup):
    COMMANDS_FOLDER_PATH = "commands"
    COMMANDS_PACKAGE_NAME = "commands"

    def list_commands(self, ctx) -> list[str]:
        rv = []
        try:
            prefix = os.path.join(os.path.dirname(__file__), self.COMMANDS_FOLDER_PATH)
            for filename in os.listdir(prefix):
                if (
                    not filename.startswith(".")
                    and not filename.startswith("_")
                    and os.path.isdir(os.path.join(prefix, filename))
                ):
                    rv.append(filename)
                elif filename.endswith(".py") and filename != "__init__.py":
                    rv.append(filename[:-3])
            rv.sort()
            return rv
        except OSError as e:
            pc.logging.error("Failed to list commands: %s", e)
            return []

    def get_command(self, _ctx, name: str) -> click.Command:
        if not name in self.list_commands(_ctx):
            raise click.ClickException(f"Unknown command: {name}")

        if not name.isalnum():
            raise click.ClickException(f"Invalid command name: {name}")

        try:
            mod = importlib.import_module("." + self.COMMANDS_PACKAGE_NAME + "." + name, package="partcad_cli.click")
            cmd_object = getattr(mod, "cli")
            if not isinstance(cmd_object, click.BaseCommand):
                raise ValueError(f"Lazy loading of {name} failed by returning " "a non-command object")
            return cmd_object
        except ModuleNotFoundError as e:
            pc.logging.exception(e)
            raise click.ClickException(f"Failed to load command '{name}'") from e
        except SyntaxError as e:
            pc.logging.exception(e)
            raise click.ClickException(f"Command '{name}' contains invalid Python code") from e
