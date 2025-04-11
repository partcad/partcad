import os
import sys
import subprocess
import shlex
import platform
from typing import Optional, List, Dict, Union, Any, Tuple, IO

# Import the encoding handler
from .encoding_handler import EncodingHandler


class SubprocessRunner:
    """
    A wrapper for subprocess execution with proper encoding handling.
    """

    def __init__(self, encoding_handler: Optional[EncodingHandler] = None):
        """
        Initialize the subprocess runner.

        Args:
            encoding_handler: Encoding handler instance
        """
        self.encoding_handler = encoding_handler or EncodingHandler()
        self.encoding_handler.apply_encoding_fixes()
        self.is_windows = platform.system() == "Windows"

    def run(
        self,
        cmd: Union[str, List[str]],
        capture_output: bool = False,
        check: bool = False,
        shell: bool = False,
        cwd: Optional[str] = None,
        env: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> subprocess.CompletedProcess:
        """
        Run a command with proper encoding handling.

        Args:
            cmd: Command to run (string or list)
            capture_output: Whether to capture stdout and stderr
            check: Whether to check for errors
            shell: Whether to run in a shell
            cwd: Working directory
            env: Environment variables
            **kwargs: Additional subprocess.run arguments

        Returns:
            subprocess.CompletedProcess: Result of subprocess execution
        """
        # Set default encoding settings
        subprocess_kwargs = {}

        # Handle text mode and encoding
        if "text" not in kwargs and "universal_newlines" not in kwargs:
            subprocess_kwargs["text"] = True

        if kwargs.get("text", kwargs.get("universal_newlines", False)) or subprocess_kwargs.get("text", False):
            subprocess_kwargs["encoding"] = kwargs.get("encoding", "utf-8")
            subprocess_kwargs["errors"] = kwargs.get("errors", "replace")

        # Set up stdout/stderr pipes for capture
        if capture_output and "stdout" not in kwargs and "stderr" not in kwargs:
            subprocess_kwargs["stdout"] = subprocess.PIPE
            subprocess_kwargs["stderr"] = subprocess.PIPE

        # Add other provided kwargs
        subprocess_kwargs.update(kwargs)

        # Set working directory
        if cwd:
            subprocess_kwargs["cwd"] = cwd

        # Set environment variables
        merged_env = None
        if env:
            merged_env = os.environ.copy()
            merged_env.update(env)
            # Ensure PYTHONIOENCODING is set for child processes
            if "PYTHONIOENCODING" not in merged_env:
                merged_env["PYTHONIOENCODING"] = "utf-8"
            subprocess_kwargs["env"] = merged_env

        # Execute the command
        try:
            result = subprocess.run(cmd, shell=shell, check=check, **subprocess_kwargs)
            return result
        except subprocess.SubprocessError as e:
            # Handle subprocess errors
            if check:
                raise
            # Create a minimal CompletedProcess-like object with the error
            return subprocess.CompletedProcess(
                args=cmd,
                returncode=1,
                stdout=None,
                stderr=(
                    str(e).encode(sys.stderr.encoding or "utf-8")
                    if not subprocess_kwargs.get("text", False)
                    else str(e)
                ),
            )

    def run_with_output(self, cmd: Union[str, List[str]], **kwargs) -> Tuple[int, str, str]:
        """
        Run a command and return returncode, stdout, and stderr.

        Args:
            cmd: Command to run
            **kwargs: Additional arguments for subprocess.run

        Returns:
            Tuple[int, str, str]: Returncode, stdout, and stderr
        """
        result = self.run(cmd, capture_output=True, text=True, **kwargs)

        stdout = result.stdout or ""
        stderr = result.stderr or ""

        # Ensure proper string decoding
        if isinstance(stdout, bytes):
            stdout = self.encoding_handler.safe_decode(stdout)
        if isinstance(stderr, bytes):
            stderr = self.encoding_handler.safe_decode(stderr)

        return result.returncode, stdout, stderr

    def run_piped(self, commands: List[Union[str, List[str]]], **kwargs) -> Tuple[int, str, str]:
        """
        Run a series of piped commands.

        Args:
            commands: List of commands to run in a pipeline
            **kwargs: Additional arguments for subprocess.run

        Returns:
            Tuple[int, str, str]: Returncode, stdout, and stderr of the final command
        """
        if not commands:
            return 0, "", ""

        if len(commands) == 1:
            return self.run_with_output(commands[0], **kwargs)

        # Initialize the pipeline
        prev_process = None
        processes = []

        # Set up environment
        env = kwargs.get("env", None)
        merged_env = None
        if env:
            merged_env = os.environ.copy()
            merged_env.update(env)
            # Ensure PYTHONIOENCODING is set for child processes
            if "PYTHONIOENCODING" not in merged_env:
                merged_env["PYTHONIOENCODING"] = "utf-8"

        # Start the first process
        cmd = commands[0]
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)

        prev_process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
        )

        processes.append(prev_process)

        # Set up the pipeline
        for i in range(1, len(commands) - 1):
            cmd = commands[i]
            if isinstance(cmd, str):
                cmd = shlex.split(cmd)

            curr_process = subprocess.Popen(
                cmd,
                stdin=prev_process.stdout,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                env=merged_env,
            )

            # Close the previous stdout to allow the previous process to receive SIGPIPE
            prev_process.stdout.close()

            processes.append(curr_process)
            prev_process = curr_process

        # Set up the final process
        cmd = commands[-1]
        if isinstance(cmd, str):
            cmd = shlex.split(cmd)

        final_process = subprocess.Popen(
            cmd,
            stdin=prev_process.stdout,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=merged_env,
        )

        # Close the previous stdout
        prev_process.stdout.close()

        # Wait for the final process to complete
        stdout, stderr = final_process.communicate()

        # Collect stderr from all processes
        all_stderr = stderr if stderr else ""
        for proc in processes:
            if proc.stderr:
                _, proc_stderr = proc.communicate()
                if proc_stderr:
                    all_stderr += proc_stderr

        return final_process.returncode, stdout, all_stderr


def run_command(cmd: Union[str, List[str]], **kwargs) -> subprocess.CompletedProcess:
    """
    Convenience function to run a command with proper encoding handling.

    Args:
        cmd: Command to run
        **kwargs: Additional arguments for subprocess.run

    Returns:
        subprocess.CompletedProcess: Result of subprocess execution
    """
    runner = SubprocessRunner()
    return runner.run(cmd, **kwargs)


def run_command_with_output(cmd: Union[str, List[str]], **kwargs) -> Tuple[int, str, str]:
    """
    Convenience function to run a command and get its output with proper encoding handling.

    Args:
        cmd: Command to run
        **kwargs: Additional arguments for subprocess.run

    Returns:
        Tuple[int, str, str]: Returncode, stdout, and stderr
    """
    runner = SubprocessRunner()
    return runner.run_with_output(cmd, **kwargs)


def run_piped_commands(commands: List[Union[str, List[str]]], **kwargs) -> Tuple[int, str, str]:
    """
    Convenience function to run a series of piped commands with proper encoding handling.

    Args:
        commands: List of commands to run in a pipeline
        **kwargs: Additional arguments for subprocess.run

    Returns:
        Tuple[int, str, str]: Returncode, stdout, and stderr of the final command
    """
    runner = SubprocessRunner()
    return runner.run_piped(commands, **kwargs)


def patch_subprocess_module():
    """
    Monkey patch the subprocess module for safer encoding handling.
    This makes all subprocess.run calls in the application safer by default.
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

    # Replace the original function with our safer version
    subprocess.run = safe_run

    # Also patch Popen for completeness
    original_popen = subprocess.Popen

    def safe_popen(cmd, *args, **kwargs):
        # Set default encoding for text mode
        if kwargs.get("text", kwargs.get("universal_newlines", False)):
            kwargs["encoding"] = kwargs.get("encoding", "utf-8")
            kwargs["errors"] = kwargs.get("errors", "replace")

        return original_popen(cmd, *args, **kwargs)

    subprocess.Popen = safe_popen

    return True
