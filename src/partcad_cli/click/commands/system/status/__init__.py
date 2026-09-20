#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksandr Ilin
# Created: 2024-02-18
#
# Licensed under Apache License, Version 2.0.
#


import os
import threading

import rich_click as click
from opentelemetry import context as otel_context

import partcad as pc
import partcad.user_config as user_config
from partcad_cli.click.cli_context import CliContext
from partcad_utils import conda as pc_conda
from partcad_utils.utils import directory_size_mb

from .. import SystemCommands

path = user_config.internal_state_dir


class StatusCommands(SystemCommands):
    """The subcommands of `pc system status`, loaded from the directory beside this file.

    `pc system status` reports the internal data -- the caches, the sandboxes,
    the disk they take. `config` and `env` report the other two things somebody
    diagnosing this machine reaches for: what the configuration resolved to, and
    what the process environment said. All three are one command because they
    answer one question, "what is this installation actually doing", and because
    each has a `pc daemon status ...` counterpart that answers it for the other
    side of the daemon boundary.
    """

    COMMANDS_FOLDER_PATH = os.path.join(SystemCommands.COMMANDS_FOLDER_PATH, "status")
    COMMANDS_PACKAGE_NAME = SystemCommands.COMMANDS_PACKAGE_NAME + ".status"


def get_total(context):
    """Report the size of the whole internal state directory."""
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "total"):
        total = directory_size_mb(path)
        pc.logging.info("Total internal data storage size: %.2fMB" % total)
    otel_context.detach(token)


def get_git(context):
    """Report the size of the git clone cache."""
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "git"):
        git_path = os.path.join(path, "git")
        git_total = directory_size_mb(git_path)
        pc.logging.info("Git cache size: %.2fMB" % git_total)
    otel_context.detach(token)


def get_tar(context):
    """Report the size of the unpacked tarball cache."""
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "tar"):
        tar_path = os.path.join(path, "tar")
        tar_total = directory_size_mb(tar_path)
        pc.logging.info("Tar cache size: %.2fMB" % tar_total)
    otel_context.detach(token)


def get_sandbox(context):
    """Report the size of the conda sandbox environments."""
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "sandbox"):
        sandbox_path = os.path.join(path, "sandbox")
        sandbox_total = directory_size_mb(sandbox_path)
        pc.logging.info("Sandbox environments size: %.2fMB" % sandbox_total)
    otel_context.detach(token)


def get_conda(context):
    """Report the size of the bundled conda's package cache.

    Only the standalone bundle's conda keeps anything here -- a host conda has a
    package cache of its own and is left alone. It is reported separately from
    the sandboxes because it is the larger of the two and the less obvious: the
    environments are what the user asked for, this is what they were built from.
    """
    token = otel_context.attach(context)
    with pc.logging.Action("Status", "conda"):
        conda_path = os.path.join(path, pc_conda.ROOT_PREFIX_SUBDIR)
        conda_total = directory_size_mb(conda_path)
        pc.logging.info("Conda package cache size: %.2fMB" % conda_total)
    otel_context.detach(token)


# 'invoke_without_command' (and the 'no_args_is_help' that follows from it,
# spelled out because 'Loader.parse_args' reads it) is what keeps a bare
# `pc system status` printing the report it always printed, now that the command
# has grown subcommands. A group that only ever printed its own help would be a
# silent behaviour change for every script and every docs page that runs it.
@click.command(
    cls=StatusCommands,
    invoke_without_command=True,
    no_args_is_help=False,
    help="Display the state of internal data used by PartCAD",
)
@click.pass_context
def cli(ctx: click.Context) -> None:
    """What PartCAD has put on this machine, and what it costs in disk.

    The group's own report, and the one of the three that is about neither the
    configuration nor the environment: where the internal state directory is,
    which tags this host answers an `unless:` with, and how much each cache,
    sandbox and package store has grown to. `config` and `env` beside it answer
    the other two questions somebody diagnosing this installation asks.
    """
    if ctx.invoked_subcommand is not None:
        return

    cli_ctx: CliContext = ctx.obj
    with pc.telemetry.set_context(cli_ctx.otel_context):
        with pc.logging.Process("Status", "global"):

            pc.logging.info(f"PartCAD version: {pc.__version__}")

            # The tags this machine has, and therefore what a package's
            # 'unless' is answered against here. Worth stating: a package
            # skipping itself is a decision made from these, and "which tags do
            # I have?" is otherwise only answerable by reading the source.
            pc.logging.info("Tags: %s" % ", ".join(sorted(pc.tags.context_tags(pc.user_config))))

            # TODO-108: @alexanderilyin: show detail about loaded partcad.yaml
            pc.logging.info("Internal data storage location: %s" % path)

            # Create threads
            thread_total = threading.Thread(target=get_total, args=(otel_context.get_current(),))
            thread_git = threading.Thread(target=get_git, args=(otel_context.get_current(),))
            thread_tar = threading.Thread(target=get_tar, args=(otel_context.get_current(),))
            thread_sandbox = threading.Thread(target=get_sandbox, args=(otel_context.get_current(),))
            thread_conda = threading.Thread(target=get_conda, args=(otel_context.get_current(),))

            # Launch threads
            thread_total.start()
            thread_git.start()
            thread_tar.start()
            thread_sandbox.start()
            thread_conda.start()

            # Wait for threads to finish
            thread_total.join()
            thread_git.join()
            thread_tar.join()
            thread_sandbox.join()
            thread_conda.join()
