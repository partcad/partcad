from rich_click import RichGroup
import rich_click as click
import logging
import os


class Loader(RichGroup):

    COMMANDS_FOLDER = os.path.join(os.path.dirname(__file__), "commands")

    def list_commands(self, ctx) -> list[str]:
        rv = []
        try:
            for filename in os.listdir(self.COMMANDS_FOLDER):
                if filename.endswith(".py") and filename != "__init__.py":
                    rv.append(filename[:-3])
            rv.sort()
            return rv
        except OSError as e:
            logging.error("Failed to list commands: %s", e)
            return []

    def get_command(self, ctx, name: str) -> click.Command:
        if not name.isalnum():
            raise click.ClickException("Invalid command name")

        ns = {}
        fn = os.path.join(self.COMMANDS_FOLDER, name + ".py")
        logging.debug("Loading %s", fn)

        if not os.path.exists(fn) or not os.path.isfile(fn):
            raise click.ClickException(f"Command '{name}' not found")

        try:
            with open(fn) as f:
                exec(f.read(), ns, ns)
            if "cli" not in ns:
                raise click.ClickException(f"Command '{name}' is invalid: missing 'cli' attribute")
            return ns["cli"]
        except OSError as e:
            logging.exception(e)
            raise click.ClickException(f"Failed to load command '{name}'") from e
        except SyntaxError as e:
            logging.exception(e)
            raise click.ClickException(f"Command '{name}' contains invalid Python code") from e
