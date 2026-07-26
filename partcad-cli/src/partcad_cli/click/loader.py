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

    def parse_args(self, ctx, args):
        # Click 8.2 turned "a group invoked with no subcommand" into a usage
        # error, so it prints the help and then exits 2 instead of 0. Bare
        # commands like `pc list` are documented as the way to see what is
        # available (docs/source/tutorial.rst) and features/docs.feature
        # asserts they exit 0, so keep the older, successful behaviour.
        if not args and self.no_args_is_help and not ctx.resilient_parsing:
            click.echo(ctx.get_help(), color=ctx.color)
            ctx.exit()
        return super().parse_args(ctx, args)

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
            raise click.ClickException(f"Unknown command: '{name}'. Try `--help`.")

        if not name.isalnum():
            raise click.ClickException(f"Invalid command name: {name}")

        try:
            mod = importlib.import_module("." + self.COMMANDS_PACKAGE_NAME + "." + name, package="partcad_cli.click")
            cmd_object = getattr(mod, "cli")
            # 'click.Command', not the deprecated 'click.BaseCommand', which
            # click 9 removes.
            if not isinstance(cmd_object, click.Command):
                raise ValueError(f"Lazy loading of {name} failed by returning " "a non-command object")
            # Every module names its command object 'cli', so that is the name
            # click derives, and help output listed each subcommand as "cli".
            # It used to be masked because the old formatter printed the key
            # from list_commands(); rich-click 1.9 prints 'cmd.name'. The name
            # is what the user types, so make the object agree with it.
            if cmd_object.name != name:
                cmd_object.name = name
            return cmd_object
        except ModuleNotFoundError as e:
            pc.logging.exception(e)
            raise click.ClickException(f"Failed to load command '{name}'") from e
        except SyntaxError as e:
            pc.logging.exception(e)
            raise click.ClickException(f"Command '{name}' contains invalid Python code") from e
