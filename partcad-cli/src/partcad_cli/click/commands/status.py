#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksandr Ilin
# Created: 2024-02-18
#
# Licensed under Apache License, Version 2.0.
#


import rich_click as click
import os
import threading

import partcad as pc
import partcad.user_config as user_config
from opentelemetry import context as otel_context
from partcad_cli.click.cli_context import CliContext


path = user_config.internal_state_dir


def get_size(start_path="."):
    total_size = 0
    for dirpath, _dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def get_total(context):
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "total"):
        total = (get_size(path)) / 1048576.0
        pc.logging.info("Total internal data storage size: %.2fMB" % total)
    otel_context.detach(token)


def get_git(context):
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "git"):
        git_path = os.path.join(path, "git")
        git_total = (get_size(git_path)) / 1048576.0
        pc.logging.info("Git cache size: %.2fMB" % git_total)
    otel_context.detach(token)


def get_tar(context):
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "tar"):
        tar_path = os.path.join(path, "tar")
        tar_total = (get_size(tar_path)) / 1048576.0
        pc.logging.info("Tar cache size: %.2fMB" % tar_total)
    otel_context.detach(token)


def get_sandbox(context):
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "sandbox"):
        sandbox_path = os.path.join(path, "sandbox")
        sandbox_total = (get_size(sandbox_path)) / 1048576.0
        pc.logging.info("Sandbox environments size: %.2fMB" % sandbox_total)
    otel_context.detach(token)


@click.command(help="Display the state of internal data used by PartCAD")
@click.pass_obj
def cli(cli_ctx: CliContext) -> None:
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("Status", "global"):

            pc.logging.info(f"PartCAD version: {pc.__version__}")

            # TODO-108: @alexanderilyin: show detail about loaded partcad.yaml
            pc.logging.info("Internal data storage location: %s" % path)

            # Create threads
            thread_total = threading.Thread(target=get_total, args=(otel_context.get_current(),))
            thread_git = threading.Thread(target=get_git, args=(otel_context.get_current(),))
            thread_tar = threading.Thread(target=get_tar, args=(otel_context.get_current(),))
            thread_sandbox = threading.Thread(target=get_sandbox, args=(otel_context.get_current(),))

            # Launch threads
            thread_total.start()
            thread_git.start()
            thread_tar.start()
            thread_sandbox.start()

            # Wait for threads to finish
            thread_total.join()
            thread_git.join()
            thread_tar.join()
            thread_sandbox.join()
