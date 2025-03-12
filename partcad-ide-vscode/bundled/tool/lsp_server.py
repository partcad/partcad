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
"""Implementation of tool support over LSP."""
from __future__ import annotations

import atexit
import base64
import copy
import json
import logging
import os
import pathlib
import re
import select
import sys
import threading
import time
import importlib
import traceback
from typing import Any, Optional, Sequence

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
from packaging.specifiers import SpecifierSet

WORKSPACE_SETTINGS = {}
GLOBAL_SETTINGS = {}
RUNNER = pathlib.Path(__file__).parent / "lsp_runner.py"

MAX_WORKERS = 5
# TODO: Update the language server name and version.
LSP_SERVER = server.LanguageServer(name="PartCAD", version="0.7.123", max_workers=MAX_WORKERS)


# **********************************************************
# Tool specific code goes below this.
# **********************************************************

# Reference:
#  LS Protocol:
#  https://microsoft.github.io/language-server-protocol/specifications/specification-3-16/
#
#  Sample implementations:
#  Pylint: https://github.com/microsoft/vscode-pylint/blob/main/bundled/tool
#  Black: https://github.com/microsoft/vscode-black-formatter/blob/main/bundled/tool
#  isort: https://github.com/microsoft/vscode-isort/blob/main/bundled/tool

TOOL_MODULE = "partcad"

TOOL_DISPLAY = "PartCAD"

TOOL_ARGS = []  # default arguments always passed to your tool.


partcad: object = None
partcad_ctx: object = None
package_path: str = None
partcad_log_thread: threading.Thread = None
partcad_log_pipe = None
partcad_log_w_stream = None

logging.basicConfig()
logging.getLogger("partcad").setLevel(logging.INFO)
logging.getLogger("partcad").propagate = False
json_rpc.logger.setLevel(logging.ERROR)


@LSP_SERVER.command("partcad.showSketch")
def show_sketch(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    sketch_name = params[0]["name"]
    package_name = params[0]["pkg"]
    if "params" in params[0]:
        params = params[0]["params"]
    else:
        params = None

    def show_sketch_internal(package_name, sketch_name, params):
        global partcad, partcad_ctx
        with partcad.logging.Process("Inspect", package_name, sketch_name):
            sketch = partcad_ctx.get_sketch(package_name + ":" + sketch_name, params)
            if sketch:
                sketch.show()

    th = threading.Thread(
        target=show_sketch_internal,
        name="vscode-partcad-cmd-show-sketch",
        args=[package_name, sketch_name, params],
    )
    th.start()
    th.join()

    LSP_SERVER.send_notification("?/partcad/showPartDone")


@LSP_SERVER.command("partcad.showInterface")
def show_interface(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    interface_name = params[0]["name"]
    package_name = params[0]["pkg"]
    if "params" in params[0]:
        params = params[0]["params"]
    else:
        params = None

    def show_interface_internal(package_name, interface_name, params):
        global partcad, partcad_ctx
        with partcad.logging.Process("Inspect", package_name, interface_name):
            interface = partcad_ctx.get_interface(package_name + ":" + interface_name)  # not yet: , params
            if interface:
                interface.show()

    th = threading.Thread(
        target=show_interface_internal,
        name="vscode-partcad-cmd-show-interface",
        args=[package_name, interface_name, params],
    )
    th.start()
    th.join()

    LSP_SERVER.send_notification("?/partcad/showPartDone")


@LSP_SERVER.command("partcad.showPart")
def show_part(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    part_name = params[0]["name"]
    package_name = params[0]["pkg"]
    if "params" in params[0]:
        params = params[0]["params"]
    else:
        params = None

    def show_part_internal(package_name, part_name, params):
        global partcad, partcad_ctx
        with partcad.logging.Process("Inspect", package_name, part_name):
            part = partcad_ctx.get_part(package_name + ":" + part_name, params)
            if part:
                part.show()

    th = threading.Thread(
        target=show_part_internal,
        name="vscode-partcad-cmd-show-part",
        args=[package_name, part_name, params],
    )
    th.start()
    th.join()

    LSP_SERVER.send_notification("?/partcad/showPartDone")


@LSP_SERVER.command("partcad.showAssembly")
def show_assembly(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    assembly_name = params[0]["name"]
    package_name = params[0]["pkg"]
    if "params" in params[0]:
        params = params[0]["params"]
    else:
        params = None

    def show_assembly_internal(package_name, assembly_name, params):
        global partcad, partcad_ctx
        with partcad.logging.Process("Inspect", package_name, assembly_name):
            assembly = partcad_ctx.get_assembly(package_name + ":" + assembly_name, params)
            if assembly:
                assembly.show()

    th = threading.Thread(
        target=show_assembly_internal,
        name="vscode-partcad-cmd-show-assembly",
        args=[package_name, assembly_name, params],
    )
    th.start()
    th.join()

    LSP_SERVER.send_notification("?/partcad/showPartDone")


@LSP_SERVER.command("partcad.regeneratePartCb")
def regenerate_part_cb(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    part_name = params[0]["name"]
    package_name = params[0]["pkg"]
    if "config" in params[0]:
        config = params[0]["config"]
    else:
        config = {}

    with partcad.logging.Process("Regenerate", package_name, part_name):
        try:
            project = partcad_ctx.get_project(package_name)
            part_config = project.get_part_config(part_name)
            part_config_update = {}

            properties_to_copy = [
                "type",
                "provider",
                "desc",
                "tokens",
                "model",
                "temperature",
                "top_p",
                "top_k",
            ]
            for prop in properties_to_copy:
                if prop in config:
                    if config[prop] is not None:
                        part_config[prop] = config[prop]
                        part_config_update[prop] = config[prop]
                    else:
                        if prop in part_config:
                            del part_config[prop]
                        part_config_update[prop] = None
            if len(part_config_update.keys()) > 0:
                project.update_part_config(part_name, part_config_update)

            if part_name in project.parts:
                # Unreference the existing part object as it has an old config
                del project.parts[part_name]
            part = partcad_ctx.get_part(package_name + ":" + part_name)
            part.regenerate()
        except Exception as e:
            partcad.logging.exception(e)
            raise e
    show_part(params)


@LSP_SERVER.command("partcad.changePartCb")
def change_part_cb(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    part_name = params[0]["name"]
    package_name = params[0]["pkg"]
    if "config" in params[0]:
        config = params[0]["config"]
    else:
        config = {}

    with partcad.logging.Process("Change", package_name, part_name):
        try:
            project = partcad_ctx.get_project(package_name)
            part_config = project.get_part_config(part_name)
            part_config_update = {}

            properties_to_copy = [
                "type",
                "provider",
                "desc",
                "tokens",
                "model",
                "temperature",
                "top_p",
                "top_k",
            ]
            for prop in properties_to_copy:
                if prop in config:
                    if config[prop] is not None:
                        part_config[prop] = config[prop]
                        part_config_update[prop] = config[prop]
                    else:
                        if prop in part_config:
                            del part_config[prop]
                        part_config_update[prop] = None
            if len(part_config_update.keys()) > 0:
                project.update_part_config(part_name, part_config_update)

            if part_name in project.parts:
                # Unreference the existing part object as it has an old config
                del project.parts[part_name]
            part = partcad_ctx.get_part(package_name + ":" + part_name)
            part.do_change(change=config.get("change", None))
            del project.parts[part_name]
        except Exception as e:
            partcad.logging.exception(e)
            raise e
    show_part(params)


@LSP_SERVER.command("partcad.exportPart")
def export_part(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    exportType = params[0]
    path = params[1]
    package_name = params[2]
    part_name = params[3]
    params = params[4]

    def export_part_internal(package_name, part_name, params):
        global partcad, partcad_ctx
        with partcad.logging.Process("Export", package_name, part_name):
            part = partcad_ctx.get_part(package_name + ":" + part_name, params)
            if part:
                if exportType == "svg":
                    part.render_svg(filepath=path)
                if exportType == "png":
                    part.render_png(filepath=path)
                if exportType == "step":
                    part.render_step(filepath=path)
                if exportType == "stl":
                    part.render_stl(filepath=path)
                if exportType == "3mf":
                    part.render_3mf(filepath=path)
                if exportType == "threejs":
                    part.render_threejs(filepath=path)
                if exportType == "obj":
                    part.render_obj(filepath=path)

    th = threading.Thread(
        target=export_part_internal,
        name="vscode-partcad-cmd-export-part",
        args=[package_name, part_name, params],
    )
    th.start()
    th.join()

    LSP_SERVER.send_notification("?/partcad/exportPartDone")


@LSP_SERVER.command("partcad.exportAssembly")
def export_assembly(params: lsp.ExecuteCommandParams = None):
    global partcad_ctx
    if partcad_ctx is None:
        return

    exportType = params[0]
    path = params[1]
    package_name = params[2]
    assembly_name = params[3]
    params = params[4]

    def export_assembly_internal(package_name, assembly_name, params):
        global partcad, partcad_ctx
        with partcad.logging.Process("Export", package_name, assembly_name):
            assembly = partcad_ctx.get_assembly(package_name + ":" + assembly_name, params)
            if assembly:
                if exportType == "svg":
                    assembly.render_svg(filepath=path)
                if exportType == "png":
                    assembly.render_png(filepath=path)
                if exportType == "step":
                    assembly.render_step(filepath=path)
                if exportType == "stl":
                    assembly.render_stl(filepath=path)
                if exportType == "3mf":
                    assembly.render_3mf(filepath=path)
                if exportType == "threejs":
                    assembly.render_threejs(filepath=path)
                if exportType == "obj":
                    assembly.render_obj(filepath=path)

    th = threading.Thread(
        target=export_assembly_internal,
        name="vscode-partcad-cmd-export-assembly",
        args=[package_name, assembly_name, params],
    )
    th.start()
    th.join()

    LSP_SERVER.send_notification("?/partcad/exportPartDone")


@LSP_SERVER.command("partcad.addPartReal")
def add_part(params: lsp.ExecuteCommandParams = None):
    global partcad
    global partcad_ctx
    if partcad_ctx is None:
        return

    kind = params[0]["kind"]
    path = params[0]["path"]
    config = {}
    if "config" in params[0]:
        config = params[0]["config"]
    LSP_SERVER.send_notification("?/partcad/info", "Adding %s using the file %s" % (kind, path))

    prj = partcad_ctx.get_project(partcad.ROOT)  # TODO(clairbee):  (partcad.CURRENT)
    prj.add_part(kind, path, config)


@LSP_SERVER.command("partcad.addAssemblyReal")
def add_assembly(params: lsp.ExecuteCommandParams = None):
    global partcad
    global partcad_ctx
    if partcad_ctx is None:
        return

    kind = params[0]["kind"]
    path = params[0]["path"]
    LSP_SERVER.send_notification("?/partcad/info", "Adding assembly %s" % path)

    prj = partcad_ctx.get_project(partcad.ROOT)  # TODO(clairbee):(partcad.CURRENT)
    prj.add_assembly(kind, path)


def do_inspect_file(path: str):
    global partcad_ctx

    found = False

    for prj_name, prj in partcad_ctx.projects.items():
        for name, assy in prj.assemblies.items():
            if hasattr(assy, "orig_name") and assy.name != assy.orig_name:
                # Skip parametrized clones
                continue

            if assy.path is not None and os.path.exists(assy.path) and os.path.samefile(assy.path, path):
                paramed_names = list(filter(lambda n: n.startswith(name), prj.assemblies.keys()))
                for paramed_name in paramed_names:
                    del prj.assemblies[paramed_name]  # Invalidate all the paramterized variations

                LSP_SERVER.send_notification(
                    "?/partcad/execute",
                    {
                        "command": "partcad.inspectAssembly",
                        "args": [{"name": name, "pkg": prj_name}, {}, True],
                    },
                )
                found = True
                break
        if found:
            break

        for name, part in prj.parts.items():
            if hasattr(part, "orig_name") and part.name != part.orig_name:
                # Skip parametrized clones
                continue

            if part.path is not None and os.path.exists(part.path) and os.path.samefile(part.path, path):
                paramed_names = list(filter(lambda n: n.startswith(name), prj.parts.keys()))
                for paramed_name in paramed_names:
                    del prj.parts[paramed_name]  # Invalidate all the paramterized variations

                LSP_SERVER.send_notification(
                    "?/partcad/execute",
                    {
                        "command": "partcad.inspectPart",
                        "args": [{"name": name, "pkg": prj_name}, {}, True],
                    },
                )
                found = True
                break
        if found:
            break

        for name, sketch in prj.sketches.items():
            if hasattr(sketch, "orig_name") and sketch.name != sketch.orig_name:
                # Skip parametrized clones
                continue

            if sketch.path is not None and os.path.exists(sketch.path) and os.path.samefile(sketch.path, path):
                if name in prj.sketches:
                    # Invalidate the model
                    # TODO(clairbee): call invalidate()
                    prj.sketches[name].shape = None
                    prj.sketches[name].components = []

                paramed_names = list(filter(lambda n: n.startswith(name + ":"), prj.sketches.keys()))
                for paramed_name in paramed_names:
                    del prj.sketches[paramed_name]  # Invalidate all the paramterized variations

                LSP_SERVER.send_notification(
                    "?/partcad/execute",
                    {
                        "command": "partcad.inspectSketch",
                        "args": [{"name": name, "pkg": prj_name}, {}, True],
                    },
                )
                found = True
                break
        if found:
            break


# partcad.inspectFile is called after restart to inspect the part/assembly that was added
@LSP_SERVER.command("partcad.inspectFile")
def inspect_file(params: lsp.ExecuteCommandParams = None):
    global partcad
    global partcad_ctx
    if partcad_ctx is None:
        return

    path = params[0]
    do_inspect_file(path)


@LSP_SERVER.command("partcad.getStats")
def report_stats(params: lsp.ExecuteCommandParams = None):
    global partcad
    global partcad_ctx
    if partcad_ctx is None:
        return

    cwd = os.getcwd()
    path: str = partcad_ctx.config_path
    if path.startswith(cwd):
        path = path.replace(cwd, ".")

    partcad_ctx.stats_recalc()

    LSP_SERVER.send_notification(
        "?/partcad/stats",
        {
            "stats": {
                "path": path,
                "packages": partcad_ctx.stats_packages,
                "packagesInstantiated": partcad_ctx.stats_packages_instantiated,
                "sketches": partcad_ctx.stats_sketches,
                "sketchesInstantiated": partcad_ctx.stats_sketches_instantiated,
                "interfaces": partcad_ctx.stats_interfaces,
                "interfacesInstantiated": partcad_ctx.stats_interfaces_instantiated,
                "parts": partcad_ctx.stats_parts,
                "partsInstantiated": partcad_ctx.stats_parts_instantiated,
                "assemblies": partcad_ctx.stats_assemblies,
                "assembliesInstantiated": partcad_ctx.stats_assemblies_instantiated,
                "size": partcad_ctx.stats_memory,
            },
            "version": partcad.__version__,
        },
    )


log_thread_die: bool = False


def log_thread(p):
    global log_thread_die

    BUFSIZE = 4096

    rfd = p.fileno()
    if hasattr(os, "set_blocking"):
        os.set_blocking(rfd, False)

    # LSP_SERVER.send_notification(
    #     "?/partcad/terminal",
    #     {
    #         "line": base64.b64encode(
    #             "terminal thread is running\r\n".encode()
    #         ).decode(),
    #     },
    # )
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


load_partcad_lock = threading.RLock()


def load_partcad():
    global partcad
    global partcad_ctx
    global partcad_log_thread
    global partcad_log_pipe
    global partcad_log_w_stream
    global load_partcad_lock

    with load_partcad_lock:
        partcad_ctx = None
        if partcad is None:
            # os.nice(10)  # Minimize the disruption for the UI
            partcad = importlib.import_module("partcad")
        else:
            try:
                partcad.fini()
                partcad.logging_ansi_terminal_fini()
            except Exception as e:
                LSP_SERVER.send_notification(
                    "?/partcad/error",
                    "Failed to de-initialize PartCAD: %s." % e,
                )
            for module_name in sorted(sys.modules.keys()):
                if module_name.startswith("partcad"):
                    del sys.modules[module_name]
            # del sys.modules["partcad"]
            import partcad

            partcad = importlib.reload(partcad)

        settings = copy.deepcopy(_get_settings_by_document(None))
        if "pythonSandbox" in settings and len(settings["pythonSandbox"]) > 0:
            partcad.user_config.python_runtime = settings["pythonSandbox"]
        if "forceUpdate" in settings and len(settings["forceUpdate"]) > 0:
            partcad.user_config.force_update = settings["forceUpdate"] == "true"
        if "googleApiKey" in settings and len(settings["googleApiKey"]) > 0:
            partcad.user_config.google_api_key = settings["googleApiKey"]
        if "openaiApiKey" in settings and len(settings["openaiApiKey"]) > 0:
            partcad.user_config.openai_api_key = settings["openaiApiKey"]

        logging.basicConfig()
        logging.getLogger("partcad").propagate = False
        if "verbosity" in settings and len(settings["verbosity"]) > 0:
            if settings["verbosity"] == "debug":
                logging.getLogger("partcad").setLevel(logging.DEBUG)
            if settings["verbosity"] == "info":
                logging.getLogger("partcad").setLevel(logging.INFO)
            if settings["verbosity"] == "error":
                logging.getLogger("partcad").setLevel(logging.ERROR)
        if partcad_log_w_stream is not None:
            partcad.logging_ansi_terminal_init(stream=partcad_log_w_stream)


@LSP_SERVER.command("partcad.activate")
def do_activate(params: lsp.ExecuteCommandParams) -> None:
    """LSP handler for partcad.activate command."""
    global partcad
    try:
        load_partcad()

        partcad_requirements = SpecifierSet(">=0.7.123")
        if partcad.__version__ in partcad_requirements:
            LSP_SERVER.send_notification("?/partcad/loaded")
    except Exception as e:
        LSP_SERVER.send_notification(
            "?/partcad/error",
            "Failed to activate PartCAD: %s.\nFollow instructions in the PartCAD's Explorer view." % e,
        )


@LSP_SERVER.command("partcad.reinstall")
def do_update(params: lsp.ExecuteCommandParams) -> None:
    """LSP handler for partcad.update command."""
    do_install_partcad(params)
    do_activate(params)


@LSP_SERVER.command("partcad.initPackage")
def do_init_package(args) -> None:
    """LSP handler for partcad.initPackage command."""
    global partcad
    global partcad_ctx
    global package_path

    if partcad is None:
        # Avoid an exception if partcad is not loaded
        LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Create a package while PartCAD is not loaded")
        return

    try:
        path = None
        if isinstance(args, list) and len(args) > 0:
            path = args[0]
        elif isinstance(args, str):
            path = args

        if path is None or path == "":
            path = os.getcwd()

            settings = copy.deepcopy(_get_settings_by_document(None))
            if "packagePath" in settings and len(settings["packagePath"]) > 0:
                relPath = settings["packagePath"]
                path = os.path.join(path, relPath)
        package_path = path
        if os.path.isdir(path):
            path = os.path.join(path, "partcad.yaml")

        # LSP_SERVER.send_notification("?/partcad/info", "Loading %s..." % path)
        if partcad.create_package(path):
            partcad_ctx = partcad.init(path)
            if partcad_ctx and not partcad_ctx.broken:
                path = partcad_ctx.config_path
                LSP_SERVER.send_notification("?/partcad/packageLoaded", path)
                do_load_package_contents()
            else:
                LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        else:
            LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
            LSP_SERVER.send_notification("?/partcad/error", "Failed to create package")
    except partcad.exception.NeedsUpdateException as e:
        LSP_SERVER.send_notification("?/partcad/needsUpdate")
    except Exception as e:
        LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Failed to create package: %s" % e.with_traceback(None))


@LSP_SERVER.command("partcad.loadPackage")
def do_load_package(args) -> None:
    """LSP handler for partcad.loadPackage command."""
    global partcad
    global partcad_ctx
    global package_path

    if partcad is None:
        # Avoid an exception if partcad is not loaded
        LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Load a package while PartCAD is not loaded")
        return

    try:
        path = None
        if isinstance(args, list) and len(args) > 0:
            path = args[0]
        elif isinstance(args, str):
            path = args

        if path is None or path == "":
            path = os.getcwd()

        package_path = path
        # LSP_SERVER.send_notification("?/partcad/info", "Loading %s..." % path)
        partcad_ctx = partcad.init(path)
        # partcad_ctx.get_all_packages()  # TODO(clairbee): fix lazy loading and  remove this for performance reasons
        path = partcad_ctx.config_path
        if partcad_ctx.broken:
            raise Exception("Package YAML file is not found")
        LSP_SERVER.send_notification("?/partcad/packageLoaded", path)
        do_load_package_contents()
    except partcad.exception.NeedsUpdateException as e:
        LSP_SERVER.send_notification("?/partcad/needsUpdate")
    except Exception as e:
        LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
        if partcad_ctx and not partcad_ctx.broken:
            LSP_SERVER.send_notification(
                "?/partcad/error",
                "Failed to load package: %s" % e,
                # "?/partcad/error", "Failed to load package: %s" % e.with_traceback(None)
            )


@LSP_SERVER.command("partcad.refresh")
def do_package_refresh(args) -> None:
    """LSP handler for partcad.refresh command."""
    global partcad
    global partcad_ctx

    if partcad is None:
        # Avoid an exception if partcad is not loaded
        LSP_SERVER.send_notification("?/partcad/error", "Refreshing packages while PartCAD is not loaded")
        return

    try:
        LSP_SERVER.send_notification(
            "?/partcad/info",
            "Beginning to refresh the packages...",
        )

        def refresh():
            with partcad.logging.Process("Refresh", "this"):
                partcad.user_config.force_update = True
                partcad_ctx.get_all_packages()
                partcad.user_config.force_update = False

        th = threading.Thread(
            target=refresh,
            name="vscode-partcad-cmd-refresh",
        )
        th.start()
        th.join()

        do_load_package_contents()
        LSP_SERVER.send_notification(
            "?/partcad/info",
            "Completed refreshing the packages",
        )
    except partcad.exception.NeedsUpdateException as e:
        LSP_SERVER.send_notification("?/partcad/needsUpdate")
    except Exception as e:
        LSP_SERVER.send_notification(
            "?/partcad/error",
            "Failed to refresh the package: %s" % e.with_traceback(None),
        )


@LSP_SERVER.command("partcad.loadPackageContents")
def load_package_contents(args=list()) -> None:
    """LSP handler for partcad.loadPackageContents command."""

    if partcad is None:
        # Avoid an exception if partcad is not loaded
        LSP_SERVER.send_notification("?/partcad/error", "Loading the package content while PartCAD is not loaded")
        return

    try:
        do_load_package_contents(args)
    except partcad.exception.NeedsUpdateException as e:
        LSP_SERVER.send_notification("?/partcad/needsUpdate")
    except Exception as e:
        LSP_SERVER.send_notification(
            "?/partcad/error",
            "Failed to load package contents: %s" % e.with_traceback(None),
        )


def do_load_package_contents(args=list()) -> None:
    """Actual implementation of loading the package, reused by multiple commands above."""
    global partcad_ctx
    # TODO(clairbee): Update the javascript part (make it aware of the current project path) to fix the following:
    # name = partcad_ctx.get_current_project_path()
    name = "/"
    if isinstance(args, list) and len(args) > 0:
        name = args[0]

    with partcad.logging.Process("Load", name):
        project = partcad_ctx.get_project(name)
        if project is None or project.broken:
            if project is not None and not project.broken:
                LSP_SERVER.send_notification(
                    "?/partcad/error",
                    "Failed to load the package: %s" % name,
                )
            LSP_SERVER.send_notification("?/partcad/packageLoadFailed")
            return

        package_names = project.get_child_project_names()
        packages = list(
            map(
                lambda package_name: partcad_ctx.get_project(package_name).config_obj,
                package_names,
            )
        )

    # Extract part configs from part objects, not from the project, as we need a post-processed one
    sketches = list(
        map(
            lambda sketch: {
                **sketch.config,
                **{"item_path": (os.path.join(project.config_dir, sketch.path) if sketch.path else None)},
            },
            project.sketches.values(),
        )
    )
    interfaces = list(
        map(
            lambda interface: {
                **interface.config,
                **{"item_path": None},
            },
            project.interfaces.values(),
        )
    )
    parts = list(
        map(
            lambda part: {
                **part.config,
                **{"item_path": (os.path.join(project.config_dir, part.path) if part.path else None)},
            },
            project.parts.values(),
        )
    )
    assemblies = list(
        map(
            lambda assembly: {
                **assembly.config,
                **{"item_path": (os.path.join(project.config_dir, assembly.path) if assembly.path else None)},
            },
            project.assemblies.values(),
        )
    )
    LSP_SERVER.send_notification(
        "?/partcad/items",
        {
            "name": name,
            "packages": packages,
            "sketches": sketches,
            "interfaces": interfaces,
            "parts": parts,
            "assemblies": assemblies,
        },
    )
    report_stats()


@LSP_SERVER.command("partcad.install")
def do_install_partcad(params: lsp.ExecuteCommandParams) -> None:
    """LSP handler for partcad.install command."""
    global partcad_log_w_stream

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

        result = utils.run_module(
            module="pip",
            argv=[
                "pip",
                "install",
            ]
            + override_externally_managed
            + [
                "--user",
                # "--quiet",
                # "--quiet",
                # "--quiet",
                "--no-input",
                "--upgrade",
                "partcad-cli",
            ],
            use_stdin=False,
            add_stdout=partcad_log_w_stream,
            add_stderr=partcad_log_w_stream,
            cwd=os.getcwd(),
            source=None,
        )
        if partcad_log_w_stream is not None:
            partcad_log_w_stream.write("Done attempting to install the latest PartCAD!\r\n")
            partcad_log_w_stream.flush()

        # LSP_SERVER.send_notification("?/partcad/info", "stdout: %s" % result.stdout)
        # LSP_SERVER.send_notification("?/partcad/info", "stderr: %s" % result.stderr)

        partcad_mod = importlib.import_module("partcad")

        if result.stderr and not partcad_mod is None:
            LSP_SERVER.send_notification(
                "?/partcad/warning",
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
    except Exception as e:
        LSP_SERVER.send_notification("?/partcad/installFailed")
        LSP_SERVER.send_notification("?/partcad/error", "Failed to install PartCAD: %s" % e)


@LSP_SERVER.feature(lsp.TEXT_DOCUMENT_DID_OPEN)
def did_open(params: lsp.DidOpenTextDocumentParams) -> None:
    """LSP handler for textDocument/didOpen request."""
    document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    diagnostics: list[lsp.Diagnostic] = []
    # diagnostics: list[lsp.Diagnostic] = [{"source": "partcad"}]
    LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


@LSP_SERVER.feature(lsp.TEXT_DOCUMENT_DID_SAVE)
def did_save(params: lsp.DidSaveTextDocumentParams) -> None:
    """LSP handler for textDocument/didSave request."""

    global partcad
    global partcad_ctx
    if partcad_ctx is None:
        return

    # LSP_SERVER.send_notification(
    #     "?/partcad/info", "textDocument/didSave"
    # )

    path = LSP_SERVER.workspace.get_text_document(params.text_document.uri).path
    if path is None:
        return

    # LSP_SERVER.send_notification("?/partcad/info", "Show on save: %s" % path)

    # document = LSP_SERVER.workspace.get_document(params.text_document.uri)
    # diagnostics: list[lsp.Diagnostic] = _linting_helper(document)
    # TODO(clairbee): implement linting

    # path = LSP_SERVER.workspace.get_document(params.text_document.uri).path
    # config = {
    #     "name": "partcad-auto-save",
    #     "path": params.text_document.uri,
    #     "type": "assy",
    # }
    # partcad.init_assembly_by_config(config)

    if (
        params.text_document.uri.endswith(".assy")
        or params.text_document.uri.endswith(".py")
        or params.text_document.uri.endswith(".scad")
        or params.text_document.uri.endswith(".dxf")
        or params.text_document.uri.endswith(".svg")
    ):
        do_inspect_file(path)
    elif params.text_document.uri.endswith("partcad.yaml"):
        LSP_SERVER.send_notification("?/partcad/doRestart")

    # diagnostics: list[lsp.Diagnostic] = []
    # LSP_SERVER.publish_diagnostics(document.uri, diagnostics)


# @LSP_SERVER.feature(lsp.TEXT_DOCUMENT_DID_CLOSE)
# def did_close(params: lsp.DidCloseTextDocumentParams) -> None:
#     """LSP handler for textDocument/didClose request."""
#     document = LSP_SERVER.workspace.get_document(params.text_document.uri)
#     # Publishing empty diagnostics to clear the entries for this file.
#     LSP_SERVER.publish_diagnostics(document.uri, [])


# def _linting_helper(document: workspace.Document) -> list[lsp.Diagnostic]:
#     # TODO: Determine if your tool supports passing file content via stdin.
#     # If you want to support linting on change then your tool will need to
#     # support linting over stdin to be effective. Read, and update
#     # _run_tool_on_document and _run_tool functions as needed for your project.
#     result = _run_tool_on_document(document)
#     return _parse_output_using_regex(result.stdout) if result.stdout else []


# TODO: If your linter outputs in a known format like JSON, then parse
# accordingly. But incase you need to parse the output using RegEx here
# is a helper you can work with.
# flake8 example:
# If you use following format argument with flake8 you can use the regex below to parse it.
# TOOL_ARGS += ["--format='%(row)d,%(col)d,%(code).1s,%(code)s:%(text)s'"]
# DIAGNOSTIC_RE =
#    r"(?P<line>\d+),(?P<column>-?\d+),(?P<type>\w+),(?P<code>\w+\d+):(?P<message>[^\r\n]*)"
DIAGNOSTIC_RE = re.compile(r"")


def _parse_output_using_regex(content: str) -> list[lsp.Diagnostic]:
    lines: list[str] = content.splitlines()
    diagnostics: list[lsp.Diagnostic] = []

    # TODO: Determine if your linter reports line numbers starting at 1 (True) or 0 (False).
    line_at_1 = True
    # TODO: Determine if your linter reports column numbers starting at 1 (True) or 0 (False).
    column_at_1 = True

    line_offset = 1 if line_at_1 else 0
    col_offset = 1 if column_at_1 else 0
    for line in lines:
        if line.startswith("'") and line.endswith("'"):
            line = line[1:-1]
        match = DIAGNOSTIC_RE.match(line)
        if match:
            data = match.groupdict()
            position = lsp.Position(
                line=max([int(data["line"]) - line_offset, 0]),
                character=int(data["column"]) - col_offset,
            )
            diagnostic = lsp.Diagnostic(
                range=lsp.Range(
                    start=position,
                    end=position,
                ),
                message=data.get("message"),
                severity=_get_severity(data["code"], data["type"]),
                code=data["code"],
                source=TOOL_MODULE,
            )
            diagnostics.append(diagnostic)

    return diagnostics


# TODO: if you want to handle setting specific severity for your linter
# in a user configurable way, then look at look at how it is implemented
# for `pylint` extension from our team.
# Pylint: https://github.com/microsoft/vscode-pylint
# Follow the flow of severity from the settings in package.json to the server.
def _get_severity(*_codes: list[str]) -> lsp.DiagnosticSeverity:
    # TODO: All reported issues from linter are treated as warning.
    # change it as appropriate for your linter.
    return lsp.DiagnosticSeverity.Warning


# **********************************************************
# Linting features end here
# **********************************************************

# TODO: If your tool is a formatter then update this section.
# Delete "Formatting features" section if your tool is NOT a
# formatter.
# **********************************************************
# Formatting features start here
# **********************************************************
#  Sample implementations:
#  Black: https://github.com/microsoft/vscode-black-formatter/blob/main/bundled/tool


# @LSP_SERVER.feature(lsp.TEXT_DOCUMENT_FORMATTING)
# def formatting(params: lsp.DocumentFormattingParams) -> list[lsp.TextEdit] | None:
#     """LSP handler for textDocument/formatting request."""
#     # If your tool is a formatter you can use this handler to provide
#     # formatting support on save. You have to return an array of lsp.TextEdit
#     # objects, to provide your formatted results.

#     document = LSP_SERVER.workspace.get_document(params.text_document.uri)
#     edits = _formatting_helper(document)
#     if edits:
#         return edits

#     # NOTE: If you provide [] array, VS Code will clear the file of all contents.
#     # To indicate no changes to file return None.
#     return None


def _formatting_helper(document: workspace.Document) -> list[lsp.TextEdit] | None:
    # TODO: For formatting on save support the formatter you use must support
    # formatting via stdin.
    # Read, and update_run_tool_on_document and _run_tool functions as needed
    # for your formatter.
    result = _run_tool_on_document(document, use_stdin=True)
    if result.stdout:
        new_source = _match_line_endings(document, result.stdout)
        return [
            lsp.TextEdit(
                range=lsp.Range(
                    start=lsp.Position(line=0, character=0),
                    end=lsp.Position(line=len(document.lines), character=0),
                ),
                new_text=new_source,
            )
        ]
    return None


def _get_line_endings(lines: list[str]) -> str:
    """Returns line endings used in the text."""
    try:
        if lines[0][-2:] == "\r\n":
            return "\r\n"
        return "\n"
    except Exception:  # pylint: disable=broad-except
        return None


def _match_line_endings(document: workspace.Document, text: str) -> str:
    """Ensures that the edited text line endings matches the document line endings."""
    expected = _get_line_endings(document.source.splitlines(keepends=True))
    actual = _get_line_endings(text.splitlines(keepends=True))
    if actual == expected or actual is None or expected is None:
        return text
    return text.replace(actual, expected)


# **********************************************************
# Formatting features ends here
# **********************************************************


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


def _get_global_defaults():
    return {
        "pythonSandbox": GLOBAL_SETTINGS.get("pythonSandbox", ""),
        "googleApiKey": GLOBAL_SETTINGS.get("googleApiKey", ""),
        "openaiApiKey": GLOBAL_SETTINGS.get("openaiApiKey", ""),
        "verbosity": GLOBAL_SETTINGS.get("verbosity", "info"),
        "packagePath": GLOBAL_SETTINGS.get("packagePath", "."),
        "forceUpdate": GLOBAL_SETTINGS.get("forceUpdate", "false"),
        "path": GLOBAL_SETTINGS.get("path", []),
        "interpreter": GLOBAL_SETTINGS.get("interpreter", [sys.executable]),
        # "args": GLOBAL_SETTINGS.get("args", []),
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


# *****************************************************
# Internal execution APIs.
# *****************************************************
def _run_tool_on_document(
    document: workspace.Document,
    use_stdin: bool = False,
    extra_args: Optional[Sequence[str]] = None,
) -> utils.RunResult | None:
    """Runs tool on the given document.

    if use_stdin is true then contents of the document is passed to the
    tool via stdin.
    """
    if extra_args is None:
        extra_args = []
    if str(document.uri).startswith("vscode-notebook-cell"):
        # TODO: Decide on if you want to skip notebook cells.
        # Skip notebook cells
        return None

    if utils.is_stdlib_file(document.path):
        # TODO: Decide on if you want to skip standard library files.
        # Skip standard library python files.
        return None

    # deep copy here to prevent accidentally updating global settings.
    settings = copy.deepcopy(_get_settings_by_document(document))

    code_workspace = settings["workspaceFS"]
    cwd = settings["cwd"]

    use_path = False
    use_rpc = False
    if settings["path"]:
        # 'path' setting takes priority over everything.
        use_path = True
        argv = settings["path"]
    elif settings["interpreter"] and not utils.is_current_interpreter(settings["interpreter"][0]):
        # If there is a different interpreter set use JSON-RPC to the subprocess
        # running under that interpreter.
        argv = [TOOL_MODULE]
        use_rpc = True
    else:
        # if the interpreter is same as the interpreter running this
        # process then run as module.
        argv = [TOOL_MODULE]

    argv += TOOL_ARGS + extra_args
    # argv += TOOL_ARGS + settings["args"] + extra_args

    if use_stdin:
        # TODO: update these to pass the appropriate arguments to provide document contents
        # to tool via stdin.
        # For example, for pylint args for stdin looks like this:
        #     pylint --from-stdin <path>
        # Here `--from-stdin` path is used by pylint to make decisions on the file contents
        # that are being processed. Like, applying exclusion rules.
        # It should look like this when you pass it:
        #     argv += ["--from-stdin", document.path]
        # Read up on how your tool handles contents via stdin. If stdin is not supported use
        # set use_stdin to False, or provide path, what ever is appropriate for your tool.
        argv += []
    else:
        argv += [document.path]

    if use_path:
        # This mode is used when running executables.
        log_to_output(" ".join(argv))
        log_to_output(f"CWD Server: {cwd}")
        result = utils.run_path(
            argv=argv,
            use_stdin=use_stdin,
            cwd=cwd,
            source=document.source.replace("\r\n", "\n"),
        )
        if result.stderr:
            log_to_output(result.stderr)
    elif use_rpc:
        # This mode is used if the interpreter running this server is different from
        # the interpreter used for running this server.
        log_to_output(" ".join(settings["interpreter"] + ["-m"] + argv))
        log_to_output(f"CWD Linter: {cwd}")

        result = jsonrpc.run_over_json_rpc(
            workspace=code_workspace,
            interpreter=settings["interpreter"],
            module=TOOL_MODULE,
            argv=argv,
            use_stdin=use_stdin,
            cwd=cwd,
            source=document.source,
        )
        if result.exception:
            log_error(result.exception)
            result = utils.RunResult(result.stdout, result.stderr)
        elif result.stderr:
            log_to_output(result.stderr)
    else:
        # In this mode the tool is run as a module in the same process as the language server.
        log_to_output(" ".join([sys.executable, "-m"] + argv))
        log_to_output(f"CWD Linter: {cwd}")
        # This is needed to preserve sys.path, in cases where the tool modifies
        # sys.path and that might not work for this scenario next time around.
        with utils.substitute_attr(sys, "path", sys.path[:]):
            try:
                # TODO: `utils.run_module` is equivalent to running `python -m partcad`.
                # If your tool supports a programmatic API then replace the function below
                # with code for your tool. You can also use `utils.run_api` helper, which
                # handles changing working directories, managing io streams, etc.
                # Also update `_run_tool` function and `utils.run_module` in `lsp_runner.py`.
                result = utils.run_module(
                    module=TOOL_MODULE,
                    argv=argv,
                    use_stdin=use_stdin,
                    cwd=cwd,
                    source=document.source,
                )
            except Exception:
                log_error(traceback.format_exc(chain=True))
                raise
        if result.stderr:
            log_to_output(result.stderr)

    log_to_output(f"{document.uri} :\r\n{result.stdout}")
    return result


def _run_tool(extra_args: Sequence[str]) -> utils.RunResult:
    """Runs tool."""
    # deep copy here to prevent accidentally updating global settings.
    settings = copy.deepcopy(_get_settings_by_document(None))

    code_workspace = settings["workspaceFS"]
    cwd = settings["workspaceFS"]

    use_path = False
    use_rpc = False
    if len(settings["path"]) > 0:
        # 'path' setting takes priority over everything.
        use_path = True
        argv = settings["path"]
    elif len(settings["interpreter"]) > 0 and not utils.is_current_interpreter(settings["interpreter"][0]):
        # If there is a different interpreter set use JSON-RPC to the subprocess
        # running under that interpreter.
        argv = [TOOL_MODULE]
        use_rpc = True
    else:
        # if the interpreter is same as the interpreter running this
        # process then run as module.
        argv = [TOOL_MODULE]

    argv += extra_args

    if use_path:
        # This mode is used when running executables.
        log_to_output(" ".join(argv))
        log_to_output(f"CWD Server: {cwd}")
        result = utils.run_path(argv=argv, use_stdin=True, cwd=cwd)
        if result.stderr:
            log_to_output(result.stderr)
    elif use_rpc:
        # This mode is used if the interpreter running this server is different from
        # the interpreter used for running this server.
        log_to_output(" ".join(settings["interpreter"] + ["-m"] + argv))
        log_to_output(f"CWD Linter: {cwd}")
        result = jsonrpc.run_over_json_rpc(
            workspace=code_workspace,
            interpreter=settings["interpreter"],
            module=TOOL_MODULE,
            argv=argv,
            use_stdin=True,
            cwd=cwd,
        )
        if result.exception:
            log_error(result.exception)
            result = utils.RunResult(result.stdout, result.stderr)
        elif result.stderr:
            log_to_output(result.stderr)
    else:
        # In this mode the tool is run as a module in the same process as the language server.
        log_to_output(" ".join([sys.executable, "-m"] + argv))
        log_to_output(f"CWD Linter: {cwd}")
        # This is needed to preserve sys.path, in cases where the tool modifies
        # sys.path and that might not work for this scenario next time around.
        with utils.substitute_attr(sys, "path", sys.path[:]):
            try:
                # TODO: `utils.run_module` is equivalent to running `python -m partcad`.
                # If your tool supports a programmatic API then replace the function below
                # with code for your tool. You can also use `utils.run_api` helper, which
                # handles changing working directories, managing io streams, etc.
                # Also update `_run_tool_on_document` function and `utils.run_module` in `lsp_runner.py`.
                result = utils.run_module(module=TOOL_MODULE, argv=argv, use_stdin=True, cwd=cwd)
            except Exception:
                log_error(traceback.format_exc(chain=True))
                raise
        if result.stderr:
            log_to_output(result.stderr)

    log_to_output(f"\r\n{result.stdout}\r\n")
    return result


# *****************************************************
# Logging and notification.
# *****************************************************
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
