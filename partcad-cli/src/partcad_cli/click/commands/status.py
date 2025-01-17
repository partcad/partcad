# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksandr Ilin
# Created: 2024-02-18
#
# Licensed under Apache License, Version 2.0.
#


import rich_click as click
import sentry_sdk

import os
import threading
import socket
import hashlib
import uuid
import psutil
import time

from partcad import __version__ as version
import humanfriendly
import partcad.logging as logging
import partcad.user_config as user_config
from partcad.context import Context

transaction = None
path = user_config.internal_state_dir


@sentry_sdk.trace
def get_size(start_path="."):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


def get_total():
    with logging.Action("Status", "total", transaction=transaction):
        total = float(get_size(path))
        logging.info("Total internal data storage size: %s" % humanfriendly.format_size(total))


def get_git():
    with logging.Action("Status", "git", transaction=transaction):
        git_path = os.path.join(path, "git")
        git_total = get_size(git_path)
        logging.info("Git cache size: %s" % humanfriendly.format_size(git_total))


def get_tar():
    with logging.Action("Status", "tar", transaction=transaction):
        tar_path = os.path.join(path, "tar")
        tar_total = get_size(tar_path)
        logging.info("Tar cache size: %s" % humanfriendly.format_size(tar_total))


def get_runtime():
    with logging.Action("Status", "runtime", transaction=transaction):
        runtime_path = os.path.join(path, "runtime")
        runtime_total = get_size(runtime_path)
        logging.info("Runtime environments size: %s" % humanfriendly.format_size(runtime_total))


@click.command(help="Display the state of internal data used by PartCAD")
@click.pass_obj
def cli(ctx: Context) -> None:
    global transaction
    transaction = ctx.transaction
    span = transaction.start_child(op="status", description="Display the state of internal data used by PartCAD")
    # span = sentry_sdk.start_span(name="status")
    with logging.Process("Status", "this", transaction=ctx.transaction):

        logging.info(f"PartCAD version: {version}")

        # TODO-108: @alexanderilyin: show detail about loaded partcad.yaml
        logging.info("Internal data storage location: %s" % path)

        # Create threads
        thread_total = threading.Thread(target=get_total)
        thread_git = threading.Thread(target=get_git)
        thread_tar = threading.Thread(target=get_tar)
        thread_runtime = threading.Thread(target=get_runtime)

        # Launch threads
        thread_total.start()
        thread_git.start()
        thread_tar.start()
        thread_runtime.start()

        # Wait for threads to finish
        thread_total.join()
        thread_git.join()
        thread_tar.join()
        thread_runtime.join()
    span.finish()
