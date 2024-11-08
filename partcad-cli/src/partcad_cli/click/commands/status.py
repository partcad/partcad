# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksand Ilin
# Created: 2024-02-18
#
# Licensed under Apache License, Version 2.0.
#


import rich_click as click  # import click

import os
import threading
import logging

from partcad import __version__ as version
import partcad.logging as pc_logging
import partcad.user_config as user_config


def get_size(start_path="."):
    total_size = 0
    for dirpath, dirnames, filenames in os.walk(start_path):
        for f in filenames:
            fp = os.path.join(dirpath, f)
            # skip if it is symbolic link
            if not os.path.islink(fp):
                total_size += os.path.getsize(fp)

    return total_size


@click.command(help="* Display the state of internal data used by PartCAD")
def cli():
    with pc_logging.Process("Status", "this"):
        pc_logging.info("PartCAD version: %s" % version)

        # TODO: @alexanderilyin: show loaded partcad.yaml
        # TODO: @alexanderilyin: update test features/partcad-cli/pc.feature
        path = user_config.internal_state_dir
        pc_logging.info("Internal data storage location: %s" % path)

        def get_total():
            with pc_logging.Action("Status", "total"):
                total = (get_size(path)) / 1048576.0
                pc_logging.info("Total internal data storage size: %.2fMB" % total)

        def get_git():
            with pc_logging.Action("Status", "git"):
                git_path = os.path.join(path, "git")
                git_total = (get_size(git_path)) / 1048576.0
                pc_logging.info("Git cache size: %.2fMB" % git_total)

        def get_tar():
            with pc_logging.Action("Status", "tar"):
                tar_path = os.path.join(path, "tar")
                tar_total = (get_size(tar_path)) / 1048576.0
                pc_logging.info("Tar cache size: %.2fMB" % tar_total)

        def get_runtime():
            with pc_logging.Action("Status", "runtime"):
                runtime_path = os.path.join(path, "runtime")
                runtime_total = (get_size(runtime_path)) / 1048576.0
                pc_logging.info("Runtime environments size: %.2fMB" % runtime_total)

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
