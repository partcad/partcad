#
# PartCAD, 2024
#
# Author: Roman Kuzmenko
# Created: 2024-12-28
#
# Licensed under Apache License, Version 2.0.
#

# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License.
"""Implementation of tool support over LSP.

This is a thin LSP adapter over the transport-agnostic operations core in the
``partcad-service-json-rpc`` package. The LSP command surface (``partcad.*``
commands and ``?/partcad/*`` notifications) is unchanged, so the VS Code
extension's "python" backend behaves exactly as before; only the bodies now
delegate to the shared core, which the JSON-RPC service backend uses too.
"""

from __future__ import annotations

import atexit
import base64
import copy
import importlib
import json
import logging
import os
import pathlib
import select
import sys
import threading
import time
from typing import Any, Optional

from lsp_server_pipe import *


# **********************************************************
# Update sys.path before importing any bundled libraries.
# **********************************************************
def update_sys_path(path_to_add: str, strategy: str) -> None:
    """Add given path to `sys.path`."""
    if path_to_add not in sys.path and os.path.isdir(path_to_add):
        if strategy == "useBundled":
            sys.path.insert(0, path_to_add)
        elif strategy == "fromEnvironment":
            sys.path.append(path_to_add)


# Ensure that we can import LSP libraries, and other bundled libraries.
update_sys_path(
    os.fspath(pathlib.Path(__file__).parent.parent / "libs"),
    os.getenv("LS_IMPORT_STRATEGY", "useBundled"),
)

# **********************************************************
# Imports needed for the language server goes below this.
# **********************************************************
# pylint: disable=wrong-import-position,import-error
import lsp_jsonrpc as jsonrpc
import lsp_utils as utils
import lsprotocol.types as lsp
from pygls import server, uris, workspace
from pygls.protocol import json_rpc

WORKSPACE_SETTINGS = {}
GLOBAL_SETTINGS = {}
RUNNER = pathlib.Path(__file__).parent / "lsp_runner.py"

MAX_WORKERS = 5
# TODO: Update the language server name and version.
LSP_SERVER = server.LanguageServer(name="PartCAD", version="0.7.193", max_workers=MAX_WORKERS)


# **********************************************************
# Tool specific code goes below this.
# **********************************************************

TOOL_MODULE = "partcad"

TOOL_DISPLAY = "PartCAD"

TOOL_ARGS = []  # default arguments always passed to your tool.


# The shared operations core lives in `partcad-service-json-rpc`, installed at
# runtime by `partcad.install` (like `partcad` itself). It is imported lazily so
# the server starts before the bootstrap install has run.
_session = None  # partcad_service_json_rpc.core.session.Session, created lazily

# Global LSP singletons
partcad_log_thread: threading.Thread = None
partcad_log_pipe = None
partcad_log_w_stream = None

logging.basicConfig()
logging.getLogger("partcad").setLevel(logging.INFO)
logging.getLogger("partcad").propagate = False
json_rpc.logger.setLevel(logging.ERROR)


def _get_session():
    """Return the shared-core session, created once the service module imports.

    Returns None before `partcad-service-json-rpc` has been installed (the
    pre-bootstrap state), so callers behave the way the legacy server did when
    `partcad` was not yet loaded.
    """
    global _session
    if _session is None:
        try:
            from partcad_service_json_rpc.core.events import EventEmitter
            from partcad_service_json_rpc.core.session import Session
        except Exception:  # pylint: disable=broad-except
            return None
        emitter = EventEmitter(lambda event, payload: LSP_SERVER.send_notification("?/partcad/" + event, payload))
        _session = Session(emitter=emitter)
        if partcad_log_w_stream is not None:
            _session.bind_log_stream(partcad_log_w_stream)
    return _session


def _ops():
    """Import the shared operations module (available after the service install)."""
    from partcad_service_json_rpc.core import operations

    return operations


def _active_session():
    """The session, but only once a package context is loaded (else None)."""
    session = _get_session()
    if session is None or session.partcad_ctx is None:
        return None
    return session


# ---- inspection -----------------------------------------------------------


@LSP_SERVER.command("partcad.showSketch")
def show_sketch(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().inspect_sketch(session, {"package": arg["pkg"], "name": arg["name"], "params": arg.get("params")})


@LSP_SERVER.command("partcad.showInterface")
def show_interface(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().inspect_interface(session, {"package": arg["pkg"], "name": arg["name"], "params": arg.get("params")})


@LSP_SERVER.command("partcad.showPart")
def show_part(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().inspect_part(session, {"package": arg["pkg"], "name": arg["name"], "params": arg.get("params")})


@LSP_SERVER.command("partcad.showAssembly")
def show_assembly(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().inspect_assembly(session, {"package": arg["pkg"], "name": arg["name"], "params": arg.get("params")})


# ---- export ---------------------------------------------------------------


@LSP_SERVER.command("partcad.exportPart")
def export_part(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    _ops().export_part(
        session,
        {"type": params[0], "path": params[1], "package": params[2], "name": params[3], "params": params[4]},
    )


@LSP_SERVER.command("partcad.exportAssembly")
def export_assembly(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    _ops().export_assembly(
        session,
        {"type": params[0], "path": params[1], "package": params[2], "name": params[3], "params": params[4]},
    )


# ---- authoring ------------------------------------------------------------


@LSP_SERVER.command("partcad.addPartReal")
def add_part(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().add_part(
        session,
        {"kind": arg["kind"], "path": arg["path"], "package": arg["packageName"], "config": arg.get("config", {})},
    )


@LSP_SERVER.command("partcad.addAssemblyReal")
def add_assembly(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().add_assembly(session, {"kind": arg["kind"], "path": arg["path"], "package": arg["packageName"]})


# ---- package helpers ------------------------------------------------------


@LSP_SERVER.command("partcad.packagePath")
def get_package_path(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().package_path(session, {"package": arg["packageName"], "callback": arg["callback"]})


# partcad.inspectFile is called after restart to inspect the part/assembly that was added
@LSP_SERVER.command("partcad.inspectFile")
def inspect_file(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    _ops().inspect_file(session, {"path": params[0]})


@LSP_SERVER.command("partcad.testReal")
def test_obj(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    arg = params[0]
    _ops().test(session, {"package": arg["packageName"], "object": arg["objectName"]})


# partcad.lintFile checks one ASSY file and answers with positioned diagnostics.
#
# Deliberately not an operation on the shared core: checking a file is the
# client's own work on the client's own file -- often an unsaved buffer -- and
# needs no context, no package graph and no CAD runtime. This server is what the
# extension runs locally under the "python" backend, so the check happens right
# here; under the "service" backend the extension runs `pc lint --file` instead.
# Either way nothing about it crosses a client-to-service boundary, which is also
# why it keeps working when the package will not load because of this very file.
@LSP_SERVER.command("partcad.lintFile")
def lint_file(params: lsp.ExecuteCommandParams = None):
    arg = params[0]
    if isinstance(arg, str):
        arg = {"path": arg}
    path = arg.get("path") or ""
    try:
        from partcad_client import lint as client_lint

        report = client_lint.check_file(path, arg.get("text"))
        return {"path": path, "diagnostics": [d.to_dict() for d in report.diagnostics]}
    except Exception as e:  # pylint: disable=broad-except
        # PartCAD may not be installed yet (pre-bootstrap), or the file may have
        # gone. Stay silent rather than turn a background check into a popup.
        log_to_output("Failed to lint %s: %s" % (path, e))
        return None


@LSP_SERVER.command("partcad.getStats")
def report_stats(params: lsp.ExecuteCommandParams = None):
    session = _active_session()
    if session is None:
        return
    _ops().info(session, {})


# **********************************************************
# Log streaming: PartCAD's ANSI terminal output is piped to
# the client as `?/partcad/terminal` notifications.
# **********************************************************
log_thread_die: bool = False


def log_thread(p):
    global log_thread_die

    BUFSIZE = 4096

    rfd = p.fileno()
    if hasattr(os, "set_blocking"):
        os.set_blocking(rfd, False)

    while not log_thread_die:
        ready, _, _ = select.select([rfd], [], [], 0.1)
        if rfd in ready:
            line = p.read(BUFSIZE)
            if len(line) == 0:
                continue
            line = line.replace(b"\n", b"\r\n")
            string = base64.b64encode(line).decode()
            LSP_SERVER.send_notification(
                "?/partcad/terminal",
                {
                    "line": string,
                },
            )


def log_thread_kill():
    global log_thread_die
    global partcad_log_thread
    global partcad_log_w_stream

    log_thread_die = True

    # TODO(clairbee): shutdown partcad's internal ansi logger thread and have it close the FD
    time.sleep(0.25)
    partcad_log_w_stream.close()

    if partcad_log_thread is not None and partcad_log_thread.is_alive():
        partcad_log_thread.join()
    partcad_log_thread = None


# ---- lifecycle ------------------------------------------------------------


@LSP_SERVER.command("partcad.activate")
def do_activate(params: lsp.ExecuteCommandParams = None) -> None:
    """LSP handler for partcad.activate command."""
    session = _get_session()
    if session is None:
        LSP_SERVER.send_notification(
            "?/partcad/error",
            "Failed to activate PartCAD: the PartCAD service module is not installed.\n"
            "Follow instructions in the PartCAD's Explorer view.",
        )
        LSP_SERVER.send_notification("?/partcad/activateFailed")
        return
    session.settings = copy.deepcopy(_get_settings_by_document(None))
    _ops().activate(session, {})


@LSP_SERVER.command("partcad.reinstall")
def do_update(params: lsp.ExecuteCommandParams = None) -> None:
    """LSP handler for partcad.reinstall command.

    Install (or update), and let the `?/partcad/installed` notification drive the
    activation: the extension answers it with `partcad.activate`, so calling
    `do_activate` here as well loaded the package twice -- and loaded it even
    when the install had just reported failure.
    """
    do_install_partcad(params)


@LSP_SERVER.command("partcad.initPackage")
def do_init_package(args) -> None:
    """LSP handler for partcad.initPackage command."""
    session = _get_session()
    if session is None:
        LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Create a package while PartCAD is not loaded")
        return

    path = None
    if isinstance(args, list) and len(args) > 0:
        path = args[0]
    elif isinstance(args, str):
        path = args
    if not path:
        path = os.getcwd()
        settings = copy.deepcopy(_get_settings_by_document(None))
        if settings.get("packagePath"):
            path = os.path.join(path, settings["packagePath"])

    _ops().init(session, {"path": path})


@LSP_SERVER.command("partcad.loadPackage")
def do_load_package(args) -> None:
    """LSP handler for partcad.loadPackage command."""
    session = _get_session()
    if session is None:
        LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Load a package while PartCAD is not loaded")
        return

    path = None
    if isinstance(args, list) and len(args) > 0:
        path = args[0]
    elif isinstance(args, str):
        path = args

    _ops().package_load(session, {"path": path or ""})


@LSP_SERVER.command("partcad.refresh")
def do_package_refresh(args) -> None:
    """LSP handler for partcad.refresh command."""
    session = _get_session()
    if session is None:
        LSP_SERVER.send_notification("?/partcad/error", "Refreshing packages while PartCAD is not loaded")
        return
    _ops().package_refresh(session, {})


@LSP_SERVER.command("partcad.installPackageReal")
def do_install_package(args=None) -> None:
    """LSP handler for partcad.installPackageReal command.

    Downloads what the *package* depends on - the PartCAD counterpart of
    ``npm install``. Not to be confused with ``partcad.install`` below, which
    bootstraps the PartCAD Python module itself.
    """
    session = _active_session()
    if session is None:
        LSP_SERVER.send_notification("?/partcad/error", "Installing the package while PartCAD is not loaded")
        return
    try:
        _ops().install(session, {})
    except Exception as e:  # pylint: disable=broad-except
        LSP_SERVER.send_notification("?/partcad/error", "Failed to install the package: %s" % e)


@LSP_SERVER.command("partcad.loadPackageContents")
def load_package_contents(args=list()) -> None:
    """LSP handler for partcad.loadPackageContents command."""
    session = _get_session()
    if session is None:
        LSP_SERVER.send_notification("?/partcad/error", "Loading the package content while PartCAD is not loaded")
        return

    name = "//"
    if isinstance(args, list) and len(args) > 0:
        name = args[0]
    _ops().list_all(session, {"name": name})


@LSP_SERVER.command("partcad.install")
def do_install_partcad(params: lsp.ExecuteCommandParams) -> None:
    """LSP handler for partcad.install command.

    Bootstraps the PartCAD service module (and, through it, `partcad`) into the
    interpreter, together with the client package this server needs for the work
    that is not the daemon's -- upgrading the installation, and checking the file
    being edited. This is specific to the "python" backend: the frozen JSON-RPC
    service already carries all of it.

    Once PartCAD *is* installed, the update that happens is the one `pc upgrade`
    performs: `partcad_client.selfupdate`, so the extension and the CLI cannot
    pick versions differently. The pip bootstrap below only runs when there is
    nothing installed yet to update.
    """
    global partcad_log_w_stream

    if _do_self_update():
        return

    try:
        import lsp_utils as utils

        pip_cmdoptions = importlib.import_module("pip._internal.cli.cmdoptions")
        if hasattr(pip_cmdoptions, "override_externally_managed"):
            override_externally_managed = ["--break-system-packages"]
        else:
            override_externally_managed = []

        if partcad_log_w_stream is not None:
            partcad_log_w_stream.write("Installing the latest PartCAD...\r\n")
            partcad_log_w_stream.flush()

        def pip_install(*packages):
            return utils.run_module(
                module="pip",
                argv=["pip", "install"]
                + override_externally_managed
                + ["--user", "--no-input", "--upgrade"]
                + list(packages),
                use_stdin=False,
                add_stdout=partcad_log_w_stream,
                add_stderr=partcad_log_w_stream,
                cwd=os.getcwd(),
                source=None,
            )

        result = pip_install(
            "partcad-service-json-rpc",
            # The client half: `partcad.lintFile` checks the edited file
            # through it, and `_do_self_update` upgrades through it. Neither
            # is a dependency of the service, which is the daemon side.
            "partcad-client",
        )

        # A separate invocation, and a non-fatal one. 'partcad-ide-client' is
        # installed alongside PartCAD rather than depended on by it: it is only
        # useful when an IDE is there to talk to, 'partcad' imports it lazily,
        # and 'show()' degrades to a warning without it. Putting it in the
        # command above would mean that one unavailable optional package took
        # PartCAD itself down with it, since pip installs nothing when any
        # requirement in a single invocation cannot be resolved.
        try:
            pip_install("partcad-ide-client")
            # Whether the install worked is decided by importing what it was
            # supposed to install, not by looking at 'stderr': 'run_module'
            # swallows pip's SystemExit, so no exit status survives, and pip
            # writes notices to 'stderr' on a perfectly successful run.
            # 'invalidate_caches' is needed because the package has just
            # appeared in a directory the import system has already scanned.
            importlib.invalidate_caches()
            importlib.import_module("partcad_ide_client")
        except Exception as e:  # pylint: disable=broad-except
            LSP_SERVER.send_notification(
                "?/partcad/warn",
                "PartCAD is installed, but 'partcad-ide-client' is not, so the PartCAD Viewer "
                "will not receive anything: %s" % e,
            )

        if partcad_log_w_stream is not None:
            partcad_log_w_stream.write("Done attempting to install the latest PartCAD!\r\n")
            partcad_log_w_stream.flush()

        partcad_mod = importlib.import_module("partcad")

        if result.stderr and not partcad_mod is None:
            LSP_SERVER.send_notification(
                "?/partcad/warn",
                "Non-fatal errors while installing PartCAD: %s" % result.stderr,
            )
            LSP_SERVER.send_notification("?/partcad/installed")
        elif result.stderr and partcad_mod is None:
            LSP_SERVER.send_notification(
                "?/partcad/error",
                "Fatal errors while installing PartCAD: %s" % result.stderr,
            )
            LSP_SERVER.send_notification("?/partcad/installFailed")
        elif partcad_mod is None:
            LSP_SERVER.send_notification(
                "?/partcad/error",
                "Failed to load PartCAD after installation!",
            )
            LSP_SERVER.send_notification("?/partcad/installFailed")
        else:
            LSP_SERVER.send_notification("?/partcad/installed")
    except Exception as e:  # pylint: disable=broad-except
        LSP_SERVER.send_notification("?/partcad/installFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Failed to install PartCAD: %s" % e)


def _do_self_update() -> bool:
    """Update an already-installed PartCAD. False when there is nothing to update.

    Returning False hands the caller back to the pip bootstrap: either PartCAD is
    not installed yet (the first run, which is what the bootstrap is for) or it
    is too old to carry `selfupdate`.

    No daemon is stopped here, and none needs to be: this backend serves the
    extension in-process and never starts one. A daemon belonging to some `pc` on
    this machine keeps running the code it already imported, and picks the new
    version up when it is next restarted.
    """
    try:
        from partcad_client import selfupdate
    except ImportError:
        return False

    def log(message: str) -> None:
        if partcad_log_w_stream is not None:
            partcad_log_w_stream.write(message.replace("\n", "\r\n") + "\r\n")
            partcad_log_w_stream.flush()

    try:
        selfupdate.update(log=log)
    except selfupdate.SelfUpdateError as e:
        # A source checkout, or an unreachable index. Neither is a reason to
        # leave the extension unusable: what is installed still works.
        LSP_SERVER.send_notification("?/partcad/warn", "PartCAD was not updated: %s" % e)
    except Exception as e:  # pylint: disable=broad-except
        LSP_SERVER.send_notification("?/partcad/installFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Failed to update PartCAD: %s" % e)
        return True

    LSP_SERVER.send_notification("?/partcad/installed")
    return True


# **********************************************************
# Document lifecycle features.
# **********************************************************
@LSP_SERVER.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    """LSP handler for textDocument/didOpen request."""
    document = LSP_SERVER.workspace.get_text_document(params.text_document.uri)
    diagnostics: list[lsp.Diagnostic] = []
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
    """LSP handler for textDocument/didSave request."""
    path = LSP_SERVER.workspace.get_text_document(params.text_document.uri).path
    if path is None:
        return

    if (
        params.text_document.uri.endswith(".assy")
        or params.text_document.uri.endswith(".py")
        or params.text_document.uri.endswith(".scad")
        or params.text_document.uri.endswith(".dxf")
        or params.text_document.uri.endswith(".svg")
    ):
        # Only this branch needs a loaded context: it looks the saved file up
        # among 'ctx.projects'. Do not gate the whole handler on it.
        session = _active_session()
        if session is None:
            return
        _ops().inspect_file(session, {"path": path})
    elif params.text_document.uri.endswith("partcad.yaml"):
        # Restarting needs no context, and the case that matters most is the one
        # where there is none: the package failed to load, and this save is the
        # user's fix for it. Gating this on a loaded context left them with a
        # dead extension until they restarted it by hand.
        LSP_SERVER.send_notification("?/partcad/doRestart")


# **********************************************************
# Required Language Server Initialization and Exit handlers.
# **********************************************************
@LSP_SERVER.feature(lsp.INITIALIZE)
def initialize(params: lsp.InitializeParams) -> None:
    """LSP handler for initialize request."""
    log_to_output(f"CWD Server: {os.getcwd()}")

    paths = "\r\n   ".join(sys.path)
    log_to_output(f"sys.path used to run Server:\r\n   {paths}")

    GLOBAL_SETTINGS.update(**params.initialization_options.get("globalSettings", {}))

    settings = params.initialization_options["settings"]
    _update_workspace_settings(settings)
    log_to_output(f"Settings used to run Server:\r\n{json.dumps(settings, indent=4, ensure_ascii=False)}\r\n")
    log_to_output(f"Global settings:\r\n{json.dumps(GLOBAL_SETTINGS, indent=4, ensure_ascii=False)}\r\n")

    global partcad_log_pipe
    global partcad_log_w_stream
    global partcad_log_thread

    # This part will only be executed once
    partcad_log_pipe = make_pipe()
    partcad_log_w_stream = partcad_log_pipe.get_write_stream()

    partcad_log_thread = threading.Thread(
        target=log_thread,
        args=[partcad_log_pipe],
        name="vscode-partcad-log-thread-" + str(time.time()),
    )
    partcad_log_thread.start()
    atexit.register(log_thread_kill)
    return {}


@LSP_SERVER.feature(lsp.EXIT)
def on_exit(_params: Optional[Any] = None) -> None:
    """Handle clean up on exit."""
    log_thread_kill()
    jsonrpc.shutdown_json_rpc()


@LSP_SERVER.feature(lsp.SHUTDOWN)
def on_shutdown(_params: Optional[Any] = None) -> None:
    """Handle clean up on shutdown."""
    log_thread_kill()
    jsonrpc.shutdown_json_rpc()


# **********************************************************
# Settings resolution.
# **********************************************************
def _get_global_defaults():
    return {
        "pythonSandbox": GLOBAL_SETTINGS.get("pythonSandbox", ""),
        "verbosity": GLOBAL_SETTINGS.get("verbosity", "info"),
        "packagePath": GLOBAL_SETTINGS.get("packagePath", "."),
        "forceUpdate": GLOBAL_SETTINGS.get("forceUpdate", "false"),
        "develIndex": GLOBAL_SETTINGS.get("develIndex", False),
        "path": GLOBAL_SETTINGS.get("path", []),
        "interpreter": GLOBAL_SETTINGS.get("interpreter", [sys.executable]),
        "importStrategy": GLOBAL_SETTINGS.get("importStrategy", "useBundled"),
        "showNotifications": GLOBAL_SETTINGS.get("showNotifications", "off"),
    }


def _update_workspace_settings(settings):
    if not settings:
        key = os.getcwd()
        WORKSPACE_SETTINGS[key] = {
            "cwd": key,
            "workspaceFS": key,
            "workspace": uris.from_fs_path(key),
            **_get_global_defaults(),
        }
        return

    for setting in settings:
        key = uris.to_fs_path(setting["workspace"])
        WORKSPACE_SETTINGS[key] = {
            "cwd": key,
            **setting,
            "workspaceFS": key,
        }


def _get_settings_by_path(file_path: pathlib.Path):
    workspaces = {s["workspaceFS"] for s in WORKSPACE_SETTINGS.values()}

    while file_path != file_path.parent:
        str_file_path = str(file_path)
        if str_file_path in workspaces:
            return WORKSPACE_SETTINGS[str_file_path]
        file_path = file_path.parent

    setting_values = list(WORKSPACE_SETTINGS.values())
    return setting_values[0]


def _get_document_key(document: workspace.Document):
    if WORKSPACE_SETTINGS:
        document_workspace = pathlib.Path(document.path)
        workspaces = {s["workspaceFS"] for s in WORKSPACE_SETTINGS.values()}

        # Find workspace settings for the given file.
        while document_workspace != document_workspace.parent:
            if str(document_workspace) in workspaces:
                return str(document_workspace)
            document_workspace = document_workspace.parent

    return None


def _get_settings_by_document(document: workspace.Document | None):
    if document is None or document.path is None:
        return list(WORKSPACE_SETTINGS.values())[0]

    key = _get_document_key(document)
    if key is None:
        # This is either a non-workspace file or there is no workspace.
        key = os.fspath(pathlib.Path(document.path).parent)
        return {
            "cwd": key,
            "workspaceFS": key,
            "workspace": uris.from_fs_path(key),
            **_get_global_defaults(),
        }

    return WORKSPACE_SETTINGS[str(key)]


# **********************************************************
# Logging and notification.
# **********************************************************
def log_to_output(message: str, msg_type: lsp.MessageType = lsp.MessageType.Log) -> None:
    LSP_SERVER.show_message_log(message, msg_type)


def log_error(message: str) -> None:
    LSP_SERVER.show_message_log(message, lsp.MessageType.Error)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["onError", "onWarning", "always"]:
        LSP_SERVER.show_message(message, lsp.MessageType.Error)


def log_warning(message: str) -> None:
    LSP_SERVER.show_message_log(message, lsp.MessageType.Warning)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["onWarning", "always"]:
        LSP_SERVER.show_message(message, lsp.MessageType.Warning)


def log_always(message: str) -> None:
    LSP_SERVER.show_message_log(message, lsp.MessageType.Info)
    if os.getenv("LS_SHOW_NOTIFICATION", "off") in ["always"]:
        LSP_SERVER.show_message(message, lsp.MessageType.Info)


# *****************************************************
# Start the server.
# *****************************************************
if __name__ == "__main__":
    LSP_SERVER.start_io()
