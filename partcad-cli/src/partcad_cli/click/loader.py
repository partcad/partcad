from rich_click import RichGroup
import rich_click as click
import logging
import os


class Loader(RichGroup):

    COMMANDS_FOLDER = os.path.join(os.path.dirname(__file__), "commands")

    def list_commands(self, ctx):
        rv = []
        for filename in os.listdir(self.COMMANDS_FOLDER):
            if filename.endswith(".py") and filename != "__init__.py":
                rv.append(filename[:-3])
        rv.sort()
        return rv

    def get_command(self, ctx, name):
        ns = {}
        fn = os.path.join(self.COMMANDS_FOLDER, name + ".py")
        logging.debug(f"Loading {fn}")
        try:
            with open(fn) as f:
                code = compile(f.read(), fn, "exec")
                eval(code, ns, ns)
            return ns["cli"]
        except Exception as e:
            logging.exception(e)
            raise click.ClickException(f"Failed to load command '{name}': {e}")
