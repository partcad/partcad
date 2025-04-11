import os
import sys
import platform
from typing import Any, Dict, List, Union

from click import Command

from .encoding_handler import EncodingHandler, patch_rich_click


class CliEncodingManager:
    """
    Manager class for handling encoding in CLI applications.
    Integrates with click and rich_click to ensure proper console output.
    """

    def __init__(self, auto_patch: bool = True, fallback_to_ascii: bool = True, prefer_plain_output: bool = False):
        """
        Initialize the CLI encoding manager.

        Args:
            auto_patch: Automatically patch rich and click modules
            fallback_to_ascii: Fall back to ASCII when Unicode is not supported
            prefer_plain_output: Prefer plain text output over rich formatting
        """
        self.handler = EncodingHandler(fallback_to_ascii=fallback_to_ascii)
        self.is_windows = platform.system() == "Windows"
        self.prefer_plain_output = prefer_plain_output
        self.unicode_supported = self.handler._is_unicode_supported()

        # Apply encoding fixes
        self.handler.apply_encoding_fixes()

        # Record original environment
        self.original_env = {
            "PYTHONIOENCODING": os.environ.get("PYTHONIOENCODING"),
            "PYTHONUTF8": os.environ.get("PYTHONUTF8"),
            "NO_COLOR": os.environ.get("NO_COLOR"),
            "TERM": os.environ.get("TERM"),
            "FORCE_COLOR": os.environ.get("FORCE_COLOR"),
        }

        if auto_patch:
            self.patch_all()

    def patch_all(self) -> None:
        """Apply all patches to ensure proper encoding in CLI."""
        # Check if Unicode is supported
        if not self.unicode_supported:
            # Set NO_COLOR environment variable to disable colors in terminals
            # that don't support Unicode
            if self.prefer_plain_output:
                os.environ["NO_COLOR"] = "1"
                os.environ["FORCE_COLOR"] = "0"

        # Patch rich_click before it's imported
        patch_rich_click()

        # Patch click if it's already imported or when it gets imported
        self._patch_click()

        # Patch subprocess module
        from .encoding_handler import patch_subprocess_module

        patch_subprocess_module()

    def _patch_click(self) -> bool:
        """
        Patch click for better encoding handling.

        Returns:
            bool: True if successful, False otherwise
        """
        # Check if click is already imported
        if "click" in sys.modules:
            try:
                import click

                # Patch click.echo for safe encoding
                original_echo = click.echo

                def safe_echo(message=None, file=None, nl=True, err=False, color=None):
                    """Safe version of click.echo that handles encoding errors gracefully."""
                    if file is None:
                        file = sys.stderr if err else sys.stdout

                    try:
                        return original_echo(message, file, nl, err, color)
                    except UnicodeEncodeError:
                        # If encoding error, try again with replace error handler
                        encoding = getattr(file, "encoding", None) or "utf-8"
                        if hasattr(message, "encode"):
                            message = message.encode(encoding, errors="replace").decode(encoding)
                        return original_echo(message, file, nl, err, color)

                click.echo = safe_echo

                # Patch click's formatting for Windows
                if self.is_windows and not self.unicode_supported:
                    click.formatting._ansi_reset_all = "\033[0m"

                return True
            except (ImportError, AttributeError):
                return False

        return False

    def setup_click_command(self, cli_function):
        """
        Decorator to set up a click command for proper encoding handling.

        Args:
            cli_function: Click CLI function or command to wrap

        Returns:
            Callable: Wrapped function or original command
        """
        if not callable(cli_function) or isinstance(cli_function, Command):
            return cli_function

        def wrapped_cli(*args, **kwargs):
            # Apply encoding fixes before running the CLI
            self.handler.apply_encoding_fixes()

            # Set up environment for click
            if not self.unicode_supported and self.prefer_plain_output:
                os.environ["NO_COLOR"] = "1"

            # Run the CLI function
            try:
                return cli_function(*args, **kwargs)
            except UnicodeError as e:
                # Handle Unicode errors
                sys.stderr.write(f"Error: Unicode encoding issue: {str(e)}\n")
                sys.stderr.write("Tip: Try setting PYTHONIOENCODING=utf-8 environment variable.\n")
                return 1
            finally:
                # Restore original environment
                for key, value in self.original_env.items():
                    if value is None:
                        if key in os.environ:
                            del os.environ[key]
                    else:
                        os.environ[key] = value

        # Preserve function metadata for click
        if hasattr(cli_function, "__name__"):
            wrapped_cli.__name__ = cli_function.__name__
        if hasattr(cli_function, "__doc__"):
            wrapped_cli.__doc__ = cli_function.__doc__

        return wrapped_cli

    def run_subprocess_safely(self, cmd: Union[str, List[str]], **kwargs) -> Any:
        """
        Run a subprocess with proper encoding handling.

        Args:
            cmd: Command to run
            **kwargs: Additional arguments for subprocess.run

        Returns:
            Any: Result of subprocess.run
        """
        return self.handler.run_subprocess(cmd, **kwargs)

    def get_terminal_info(self) -> Dict[str, str]:
        """
        Get terminal encoding information.

        Returns:
            Dict[str, str]: Dictionary with encoding information
        """
        return self.handler.get_terminal_info()


def initialize_cli():
    """
    Initialize CLI with proper encoding support.
    Call this before importing click, rich_click, or rich.

    Returns:
        CliEncodingManager: CLI encoding manager instance
    """
    manager = CliEncodingManager()
    return manager
