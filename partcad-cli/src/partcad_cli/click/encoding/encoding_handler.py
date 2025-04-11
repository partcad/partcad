import os
import sys
import locale
import platform
import subprocess
from typing import Optional, Dict, Union, List


class EncodingHandler:
    """
    A utility class to handle cross-platform encoding issues in CLI applications.
    Particularly focuses on fixing Windows-specific Unicode output problems.
    """

    def __init__(self, force_utf8: bool = False, fallback_to_ascii: bool = True):
        """
        Initialize the encoding handler.

        Args:
            force_utf8: If True, force UTF-8 encoding for all I/O operations
            fallback_to_ascii: If True, fallback to ASCII for unsupported characters
        """
        self.is_windows = platform.system() == "Windows"
        self.force_utf8 = force_utf8
        self.fallback_to_ascii = fallback_to_ascii
        self.original_stdout_encoding = sys.stdout.encoding
        self.original_stderr_encoding = sys.stderr.encoding
        self.original_preferred_encoding = locale.getpreferredencoding()
        self.utf8_mode_active = self._is_utf8_mode_active()
        self.has_applied_fixes = False

    def _is_utf8_mode_active(self) -> bool:
        """Check if Python's UTF-8 mode is active."""
        return (
            sys.flags.utf8_mode
            or os.environ.get("PYTHONUTF8", "0") == "1"
            or (self.is_windows and "UTF-8" in (sys.stdout.encoding or "").upper())
        )

    def _is_unicode_supported(self) -> bool:
        """Check if the terminal supports Unicode (UTF-8) output."""
        if not self.is_windows:
            return True

        # Check Windows console encoding
        try:
            # Try to get code page info using Windows API
            import ctypes

            kernel32 = ctypes.windll.kernel32
            code_page = kernel32.GetConsoleOutputCP()
            return code_page == 65001  # 65001 is the code page for UTF-8
        except (ImportError, AttributeError):
            # Fallback to checking environment
            return (
                self.utf8_mode_active
                or "UTF-8" in (sys.stdout.encoding or "").upper()
                or "UTF" in os.environ.get("PYTHONIOENCODING", "").upper()
            )

    def apply_encoding_fixes(self) -> bool:
        """
        Apply encoding fixes to ensure proper Unicode handling across platforms.

        Returns:
            bool: True if fixes were applied, False otherwise
        """
        if self.has_applied_fixes:
            return True

        # Set environmental variables to influence Python's encoding behavior
        if self.force_utf8:
            os.environ["PYTHONUTF8"] = "1"
            os.environ["PYTHONIOENCODING"] = "utf-8"

        if self.is_windows:
            # Try to set console code page to UTF-8 (65001) using Windows API
            self._set_windows_console_utf8()

        # Patch sys.stdout/stderr if needed
        if not self._is_unicode_supported() and self.fallback_to_ascii:
            self._patch_stdout_stderr()

        self.has_applied_fixes = True
        return True

    def _set_windows_console_utf8(self) -> bool:
        """Try to set Windows console code page to UTF-8."""
        if not self.is_windows:
            return False

        try:
            # Try to use Windows API directly
            import ctypes

            kernel32 = ctypes.windll.kernel32
            result = kernel32.SetConsoleOutputCP(65001)  # 65001 is UTF-8
            if result:
                # Also set input code page
                kernel32.SetConsoleCP(65001)
                return True
        except (ImportError, AttributeError):
            pass

        # Fallback to using subprocess
        try:
            subprocess.run(["chcp", "65001"], shell=True, check=False, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            return True
        except (subprocess.SubprocessError, FileNotFoundError):
            return False

    def _patch_stdout_stderr(self) -> None:
        """
        Patch sys.stdout and sys.stderr to handle encoding errors gracefully.
        """

        class EncodingSafeTextIOWrapper:
            def __init__(self, stream, encoding_handler):
                self.stream = stream
                self.encoding_handler = encoding_handler
                self.encoding = stream.encoding or "utf-8"

            def write(self, text):
                try:
                    return self.stream.write(text)
                except UnicodeEncodeError:
                    # Try with 'replace' error handler
                    safe_text = text.encode(self.encoding, errors="replace").decode(self.encoding)
                    return self.stream.write(safe_text)

            def __getattr__(self, attr):
                return getattr(self.stream, attr)

        # Patch stdout and stderr
        sys.stdout = EncodingSafeTextIOWrapper(sys.stdout, self)
        sys.stderr = EncodingSafeTextIOWrapper(sys.stderr, self)

    def run_subprocess(self, cmd: Union[str, List[str]], **kwargs) -> subprocess.CompletedProcess:
        """
        Run a subprocess with proper encoding handling.

        Args:
            cmd: Command to run (string or list of strings)
            **kwargs: Additional arguments to pass to subprocess.run

        Returns:
            subprocess.CompletedProcess: Result of the subprocess execution
        """
        # Make sure encoding fixes are applied
        self.apply_encoding_fixes()

        # Set default encoding parameters for subprocess
        subprocess_kwargs = {
            "text": True,
            "encoding": "utf-8",
            "errors": "replace",  # Replace invalid characters instead of crashing
        }

        # Update with user-provided kwargs
        subprocess_kwargs.update(kwargs)

        # Run subprocess
        return subprocess.run(cmd, **subprocess_kwargs)

    def safe_decode(self, data: Union[bytes, str], encoding: Optional[str] = None) -> str:
        """
        Safely decode byte data to string with graceful error handling.

        Args:
            data: Bytes or string to decode
            encoding: Encoding to use (defaults to utf-8)

        Returns:
            str: Decoded string
        """
        if isinstance(data, str):
            return data

        encodings_to_try = [
            encoding or "utf-8",
            sys.stdout.encoding,
            locale.getpreferredencoding(),
            "cp1252",  # Windows default
            "latin-1",  # Will always work but might give wrong characters
        ]

        # Remove duplicates while preserving order
        seen = set()
        encodings_to_try = [x for x in encodings_to_try if x and not (x in seen or seen.add(x))]

        # Try each encoding
        for enc in encodings_to_try:
            try:
                return data.decode(enc)
            except (UnicodeDecodeError, LookupError):
                continue

        # Fallback to latin-1 with replace
        return data.decode("latin-1", errors="replace")

    def get_terminal_info(self) -> Dict[str, str]:
        """
        Get information about terminal encoding settings.

        Returns:
            Dict[str, str]: Dictionary with encoding information
        """
        info = {
            "platform": platform.system(),
            "python_version": sys.version,
            "stdout_encoding": sys.stdout.encoding,
            "stderr_encoding": sys.stderr.encoding,
            "locale_encoding": locale.getpreferredencoding(),
            "utf8_mode": str(self._is_utf8_mode_active()),
            "unicode_supported": str(self._is_unicode_supported()),
        }

        if self.is_windows:
            try:
                import ctypes

                kernel32 = ctypes.windll.kernel32
                code_page = kernel32.GetConsoleOutputCP()
                info["windows_console_cp"] = str(code_page)
            except (ImportError, AttributeError):
                info["windows_console_cp"] = "unknown"

        return info


def configure_unicode_output():
    """
    Configure the system for proper Unicode handling.
    This is a convenience function for quick setup.
    """
    handler = EncodingHandler(force_utf8=True)
    handler.apply_encoding_fixes()
    return handler


def patch_rich_click():
    """
    Apply patches to rich_click to handle Windows encoding issues.
    Call this function before importing/using rich_click.
    """
    import importlib

    handler = EncodingHandler()
    handler.apply_encoding_fixes()

    # Check if rich_click is already imported
    if "rich_click" in sys.modules:
        # Try to reload it after our fixes
        try:
            importlib.reload(sys.modules["rich_click"])
        except (ImportError, AttributeError):
            pass

    # Monkey patch the console creation in rich
    try:
        from rich.console import Console

        original_init = Console.__init__

        def safe_console_init(self, *args, **kwargs):
            if "stderr" not in kwargs and "file" not in kwargs:
                kwargs["stderr"] = False
            if "safe_box" not in kwargs and not handler._is_unicode_supported():
                kwargs["safe_box"] = True
            if "highlight" not in kwargs:
                kwargs["highlight"] = False
            original_init(self, *args, **kwargs)

        Console.__init__ = safe_console_init

        return True
    except ImportError:
        return False


def patch_subprocess_module():
    """
    Monkey patch the subprocess module to ensure encoding safety.
    """
    original_run = subprocess.run

    def safe_run(cmd, *args, **kwargs):
        # Default to text mode with safe encoding
        if "text" not in kwargs and "universal_newlines" not in kwargs:
            kwargs["text"] = True

        # Set encoding and error handling if in text mode
        if kwargs.get("text", kwargs.get("universal_newlines", False)):
            kwargs["encoding"] = kwargs.get("encoding", "utf-8")
            kwargs["errors"] = kwargs.get("errors", "replace")

        return original_run(cmd, *args, **kwargs)

    subprocess.run = safe_run
    return True


# Apply fixes when the module is imported
encoding_handler = EncodingHandler()
