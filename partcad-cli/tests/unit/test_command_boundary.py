#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""Contract tests for the boundary between the `pc` CLI and the PartCAD daemon.

`pc` is a thin JSON-RPC client: a command body calls
``partcad_cli.click.service.run(cli_ctx, "<method>", ...)`` and the per-workspace
daemon does the work. Two rules hold that arrangement together, and both were
conventions that only broke at runtime -- or 30-60 minutes into the behave
matrix -- while the migration was in flight:

* every method name a command sends must exist in the daemon's registry, and
* a command may import the heavy ``partcad`` package only when it is one of the
  few that genuinely run in the client process.

The tests below turn both into pytest failures. They read the command tree with
:mod:`ast`: nothing here imports a command module or invokes a click command, so
they cost milliseconds and cannot be fooled by import side effects.

They live under `partcad-cli` rather than next to the daemon because CI's
`test-pytest` job (`.github/workflows/test.yml`) runs `pytest partcad
partcad-cli`; a copy under `partcad-service-json-rpc/tests` would only be
collected by the whole-repo run in `test-dev.yml`.
"""

import ast
import difflib
from collections import namedtuple
from pathlib import Path
from textwrap import dedent

import pytest
from partcad_service_json_rpc.rpc.methods import build_registry

PARTCAD_CLI_SRC = Path(__file__).resolve().parents[2] / "src" / "partcad_cli"
COMMANDS_DIR = PARTCAD_CLI_SRC / "click" / "commands"

# ---------------------------------------------------------------------------
# The command boundary.
#
# The rationale lives in partcad-cli/AGENTS.md, "Command boundary"; the short
# version is that a command belongs on the *daemon* when it reads or mutates the
# package graph or drives a CAD wrapper (whose sandboxed Python runtime lives in
# the daemon's environment and may not exist on the client at all), and stays
# *in-process* only when it works on client-only state that cannot cross the
# wire. A package-mutating command that runs in-process is worse than slow: the
# daemon's warm context keeps serving the pre-mutation package.
#
# These two dicts are the single place where the boundary is written down. Both
# map a path relative to COMMANDS_DIR to the reason it is listed, which is what
# the failure messages print. Adding a normal (thin) command needs no edit here.
# ---------------------------------------------------------------------------

# Commands that legitimately run in the client process. Every entry here is a
# deliberate decision, not a leftover -- read the reason before adding one.
IN_PROCESS = {
    "init.py": "creates the workspace itself, before any package (or daemon context) exists",
    "config.py": "prints the client's own resolved user_config, with its --threads-max/PC_* overrides",
    "healthcheck.py": "diagnoses the host the CLI runs on, which is not necessarily the daemon's",
    "daemon/start.py": "manages the daemon process itself",
    "daemon/stop.py": "manages the daemon process itself",
    "system/telemetry/clear.py": "clears the client's own telemetry id under the client's state dir",
    "system/telemetry/info.py": "reports the client's own telemetry configuration",
}

# Commands that have not been migrated to the daemon yet. This list is a debt
# ledger, not a target: it may only shrink. Nothing new belongs here -- a new
# command that needs the package graph or a CAD wrapper is written as a thin
# client from the start.
NOT_YET_MIGRATED = {
    "add/sketch.py": "not migrated yet; still builds the sketch through an in-process context",
    "add/dep.py": "not migrated yet; still edits the package config through an in-process context",
    "supply/caps.py": "supply/* is not migrated yet; still drives providers in-process",
    "supply/find.py": "supply/* is not migrated yet; still drives providers in-process",
    "supply/order.py": "supply/* is not migrated yet; still drives providers in-process",
    "supply/quote.py": "supply/* is not migrated yet; still drives providers in-process",
}

MAY_IMPORT_PARTCAD = {**IN_PROCESS, **NOT_YET_MIGRATED}

# Modules on the CLI's start-up path: `pc --help` resolves every command module
# to print its short help, and each of those imports these. `import partcad`
# costs ~1.6s, so it must never happen at module level here -- command.py's
# `from partcad.globals import init` is deliberately deferred into a function.
CLI_STARTUP_MODULES = (
    "__init__.py",
    "click/__init__.py",
    "click/command.py",
    "click/loader.py",
    "click/cli_context.py",
    "click/service.py",
)

# `partcad_utils` and `partcad_service_json_rpc` are the deliberately cheap
# packages the client is allowed to import, so the match has to be exact.
HEAVY_PACKAGE = "partcad"

CommandModule = namedtuple("CommandModule", "rel partcad_imports imports_run run_calls unresolved_run_calls")


def _is_heavy(name: str) -> bool:
    return name == HEAVY_PACKAGE or name.startswith(HEAVY_PACKAGE + ".")


def _partcad_imports(node, module_level_only: bool = False):
    """Yield ``(lineno, name)`` for every import of the heavy ``partcad`` package."""
    for child in ast.iter_child_nodes(node):
        if module_level_only and isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            # An import inside a function body is deferred: it costs nothing
            # until that function runs, so it is not a start-up cost.
            continue
        if isinstance(child, ast.Import):
            for alias in child.names:
                if _is_heavy(alias.name):
                    yield child.lineno, alias.name
        elif isinstance(child, ast.ImportFrom):
            # Relative imports (level > 0) resolve inside partcad_cli itself and
            # can never reach `partcad`.
            if child.level == 0 and child.module and _is_heavy(child.module):
                yield child.lineno, child.module
        yield from _partcad_imports(child, module_level_only)


def _service_run_bindings(tree):
    """Return the local names ``service.run`` and the ``service`` module are bound to."""
    run_names = set()
    service_names = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            for alias in node.names:
                if alias.name == "run" and (node.module or "").rsplit(".", 1)[-1] == "service":
                    run_names.add(alias.asname or alias.name)
                elif alias.name == "service":
                    service_names.add(alias.asname or alias.name)
        elif isinstance(node, ast.Import):
            for alias in node.names:
                if alias.name.rsplit(".", 1)[-1] == "service":
                    service_names.add(alias.asname or alias.name)
    return run_names, service_names


def _is_service_run_call(func, run_names, service_names) -> bool:
    """True for ``run(...)`` bound to service.run, or ``[...].service.run(...)``.

    Deliberately narrow: `asyncio.run(...)` appears all over supply/* and must
    not be mistaken for a daemon call.
    """
    if isinstance(func, ast.Name):
        return func.id in run_names
    if isinstance(func, ast.Attribute) and func.attr == "run":
        if isinstance(func.value, ast.Name):
            return func.value.id in service_names
        if isinstance(func.value, ast.Attribute):
            return func.value.attr == "service"
    return False


def _method_argument(call):
    """The ``method`` argument of ``run(cli_ctx, method, ...)``, or None."""
    for keyword in call.keywords:
        if keyword.arg == "method":
            return keyword.value
    if len(call.args) >= 2:
        return call.args[1]
    return None


def _scan_command_modules():
    modules = []
    for path in sorted(COMMANDS_DIR.rglob("*.py")):
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        run_names, service_names = _service_run_bindings(tree)
        run_calls = []
        unresolved = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call) or not _is_service_run_call(node.func, run_names, service_names):
                continue
            method = _method_argument(node)
            if isinstance(method, ast.Constant) and isinstance(method.value, str):
                run_calls.append((node.lineno, method.value))
            else:
                unresolved.append(node.lineno)
        modules.append(
            CommandModule(
                rel=path.relative_to(COMMANDS_DIR).as_posix(),
                partcad_imports=list(_partcad_imports(tree)),
                imports_run=bool(run_names or service_names),
                run_calls=run_calls,
                unresolved_run_calls=unresolved,
            )
        )
    return modules


COMMAND_MODULES = _scan_command_modules()

_BOUNDARY_RULE = """\
    The rule (partcad-cli/AGENTS.md, "Command boundary"): a command belongs on the
    DAEMON when it reads or mutates the package graph, or drives a CAD wrapper --
    the wrapper's Python runtime lives in the daemon's environment and may not
    exist on the client at all. Such a command must be a thin client
    (`from ..service import run`), because a package-mutating command that runs
    in the client process leaves the daemon's warm context serving the
    pre-mutation package. It also keeps `pc` fast: `import partcad` costs ~1.6s,
    and `pc --help` resolves every command module to print its short help.

    A command stays IN-PROCESS only when it works on client-only state that
    cannot cross the wire (`init`, `config`, `healthcheck`, `daemon start|stop`,
    `system telemetry clear|info`).

    If you moved a command across the boundary on purpose, update IN_PROCESS /
    NOT_YET_MIGRATED at the top of this file -- that is the only place the split
    is written down."""


def test_command_tree_is_discoverable():
    """Guard the scan itself: everything below is vacuous if it finds nothing."""
    assert COMMANDS_DIR.is_dir(), f"Command tree not found at {COMMANDS_DIR}"
    assert len(COMMAND_MODULES) > 20, f"Only {len(COMMAND_MODULES)} command modules found under {COMMANDS_DIR}"


def test_every_method_the_cli_calls_is_registered_by_the_daemon():
    registry = build_registry()
    offenders = [
        (module.rel, lineno, method)
        for module in COMMAND_MODULES
        for lineno, method in module.run_calls
        if method not in registry
    ]
    if offenders:
        details = []
        for rel, lineno, method in offenders:
            close = difflib.get_close_matches(method, sorted(registry), n=3, cutoff=0.5)
            hint = "closest registered: " + ", ".join(close) if close else "no similarly named method is registered"
            details.append(f"      {rel}:{lineno} calls '{method}'  ({hint})")
        pytest.fail(dedent("""
                The CLI sends JSON-RPC method names the daemon does not register. Each of
                these fails at runtime with "Method not found", and only an end-to-end run
                would have noticed:

                {details}

                Register the method in
                partcad-service-json-rpc/src/partcad_service_json_rpc/rpc/methods.py
                (the _OPERATIONS table) and implement it in ../core/operations.py -- or fix
                the name at the call site. Renaming an operation means renaming it in both
                places, in the same commit.
                """).format(details="\n".join(details)))


def test_every_daemon_call_names_its_method_with_a_string_literal():
    """A computed method name is invisible to the check above, so forbid it."""
    offenders = [(module.rel, lineno) for module in COMMAND_MODULES for lineno in module.unresolved_run_calls]
    if offenders:
        pytest.fail(dedent("""
                These service.run() calls do not pass the method name as a plain string
                literal:

                {details}

                The name is then invisible to
                test_every_method_the_cli_calls_is_registered_by_the_daemon, which is what
                keeps the CLI and the daemon's registry from drifting apart. Pass the
                literal at the call site (branch on the caller's side if a command needs
                two different methods).
                """).format(details="\n".join(f"      {rel}:{lineno}" for rel, lineno in offenders)))


def test_modules_that_import_service_run_actually_call_it():
    """Second guard on the scan: an unused import means the detector missed the call."""
    offenders = [
        module.rel
        for module in COMMAND_MODULES
        if module.imports_run and not module.run_calls and not module.unresolved_run_calls
    ]
    assert not offenders, (
        "These modules import partcad_cli.click.service but no run() call was found in them: "
        f"{', '.join(offenders)}. Either the import is dead, or the call is written in a shape "
        "_is_service_run_call() in this file does not recognize -- in which case the method-name "
        "contract test is silently skipping those calls and _is_service_run_call() needs updating."
    )


def test_thin_commands_do_not_import_partcad():
    offenders = [
        (module.rel, lineno, name)
        for module in COMMAND_MODULES
        if module.rel not in MAY_IMPORT_PARTCAD
        for lineno, name in module.partcad_imports
    ]
    if offenders:
        details = "\n".join(f"      {rel}:{lineno} imports '{name}'" for rel, lineno, name in offenders)
        pytest.fail(dedent("""
                These command modules import the heavy `partcad` package, but they are not
                on the in-process list:

                {details}

                {rule}
                """).format(details=details, rule=dedent(_BOUNDARY_RULE)))


def test_in_process_commands_do_not_call_the_daemon():
    """An in-process command that needs the daemon is misclassified, not special."""
    offenders = [
        (module.rel, lineno, method)
        for module in COMMAND_MODULES
        if module.rel in IN_PROCESS
        for lineno, method in module.run_calls
    ]
    offenders += [
        (module.rel, lineno, "<computed>")
        for module in COMMAND_MODULES
        if module.rel in IN_PROCESS
        for lineno in module.unresolved_run_calls
    ]
    if offenders:
        details = "\n".join(f"      {rel}:{lineno} calls '{method}'" for rel, lineno, method in offenders)
        pytest.fail(dedent("""
                These commands are listed as in-process, yet they call the daemon:

                {details}

                In-process means "works on client-only state that cannot cross the wire".
                A command that needs the daemon for part of its job belongs on the daemon
                side entirely -- splitting it leaves half of the work reading a context the
                other half already invalidated. Move the whole command, and drop it from
                IN_PROCESS at the top of this file.
                """).format(details=details))


def test_boundary_lists_have_no_stale_entries():
    """The lists are the contract; a stale entry silently widens it."""
    missing = [rel for rel in MAY_IMPORT_PARTCAD if not (COMMANDS_DIR / rel).is_file()]
    assert not missing, (
        f"IN_PROCESS/NOT_YET_MIGRATED name command modules that no longer exist: {', '.join(sorted(missing))}. "
        "Remove them -- a stale entry is an exemption nobody is watching."
    )

    imports_partcad = {module.rel for module in COMMAND_MODULES if module.partcad_imports}
    migrated = sorted(rel for rel in NOT_YET_MIGRATED if rel not in imports_partcad)
    assert not migrated, (
        f"These commands no longer import `partcad`, so they have been migrated: {', '.join(migrated)}. "
        "Delete them from NOT_YET_MIGRATED at the top of this file. That list is a debt ledger and may "
        "only shrink; leaving a migrated command in it would let a future in-process import back in unnoticed."
    )


def test_cli_startup_path_does_not_import_partcad_at_module_level():
    """Everything `pc` loads before dispatch, on every single invocation."""
    offenders = []
    for rel in CLI_STARTUP_MODULES:
        path = PARTCAD_CLI_SRC / rel
        assert path.is_file(), f"CLI start-up module not found: {path}"
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        offenders += [(rel, lineno, name) for lineno, name in _partcad_imports(tree, module_level_only=True)]
    if offenders:
        details = "\n".join(f"      partcad_cli/{rel}:{lineno} imports '{name}'" for rel, lineno, name in offenders)
        pytest.fail(dedent("""
                The CLI's start-up path imports the heavy `partcad` package at module
                level:

                {details}

                Every `pc` invocation pays that ~1.6s, including `pc --help` and the
                commands that only talk to the daemon. `partcad_utils` carries the pieces
                the client genuinely needs (logging, telemetry, user_config); anything
                else belongs behind a function-level import, the way
                command.py::get_partcad_context defers `from partcad.globals import init`.
                """).format(details=details))
