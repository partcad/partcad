#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-20
#
# Licensed under Apache License, Version 2.0.

import os
import shutil
import threading
import ruamel.yaml as ruamel
import sentry_sdk
from sentry_sdk.integrations.logging import LoggingIntegration

from .context import Context
from .assembly import Assembly
from .assembly_factory_assy import AssemblyFactoryAssy
from .assembly_factory_alias import AssemblyFactoryAlias
from .file_factory_url import FileFactoryUrl
from .provider_factory_manufacturer import ProviderFactoryManufacturer
from .provider_factory_enrich import ProviderFactoryEnrich
from .provider_factory_store import ProviderFactoryStore
from .part import Part
from . import consts
from . import factory
from .user_config import UserConfig, SentryConfig
from . import logging as pc_logging

__version__: str = "0.7.127"

global _partcad_context
_partcad_context = None
_partcad_context_lock = threading.Lock()

factory.register("assembly", "assy", AssemblyFactoryAssy)
factory.register("assembly", "alias", AssemblyFactoryAlias)
factory.register("file", "url", FileFactoryUrl)
factory.register("provider", "manufacturer", ProviderFactoryManufacturer)
factory.register("provider", "enrich", ProviderFactoryEnrich)
factory.register("provider", "store", ProviderFactoryStore)


def init(config_path=None, search_root=True, user_config=UserConfig()) -> Context:
    """Initialize the default context explicitly using the desired path."""
    global _partcad_context
    global _partcad_context_path
    global _partcad_context_lock

    with _partcad_context_lock:
        if _partcad_context is None:
            _partcad_context_path = config_path
            _partcad_context = Context(config_path, search_root=search_root, user_config=user_config)
            return _partcad_context

    if _partcad_context_path == config_path:
        return _partcad_context

    return Context(config_path, search_root=search_root, user_config=user_config)

def init_sentry(sentry_config: SentryConfig):
    critical_to_ignore = [
        "action_start: ",
        "action_end: ",
    ]
    debug_to_ignore = [
        "Starting action",
        "Finished action",
    ]

    def before_send(event, hint):
        # Reduce noise in logs (drop events from "with logging.Process():")
        if event.get("level") == "critical":
            # from logging_ansi_terminal.py
            message = event.get("logentry", {}).get("message")
            if message and any(message.startswith(prefix) for prefix in critical_to_ignore):
                return None
        elif event.get("level") == "debug":
            # from logging.py
            message = event.get("logentry", {}).get("message")
            if message and any(message.startswith(prefix) for prefix in debug_to_ignore):
                return None

        return event

    sentry_sdk.init(
        dsn=sentry_config.dsn,
        release=__version__,
        debug=sentry_config.debug,
        shutdown_timeout=sentry_config.shutdown_timeout,
        enable_tracing=True,
        attach_stacktrace=False,
        traces_sample_rate=sentry_config.traces_sample_rate,
        integrations=[
            LoggingIntegration(
                level=pc_logging.ERROR,
            ),
        ],
        before_send=before_send,
    )

def fini():
    global _partcad_context
    global _partcad_context_path
    global _partcad_context_lock

    with _partcad_context_lock:
        _partcad_context = None
        _partcad_context_path = None


def get_assembly(assembly_name, params=None) -> Assembly:
    """Get the assembly from the given project"""
    return init().get_assembly(assembly_name, params=params)


def get_assembly_cadquery(assembly_name, params=None) -> Assembly:
    """Get the assembly from the given project"""
    return init().get_assembly_cadquery(assembly_name, params=params)


def get_assembly_build123d(assembly_name, params=None) -> Assembly:
    """Get the assembly from the given project"""
    return init().get_assembly_build123d(assembly_name, params=params)


def get_part(part_name, params=None) -> Part:
    """Get the part from the given project"""
    return init().get_part(part_name, params=params)


def get_part_cadquery(part_name, params=None) -> Part:
    """Get the part from the given project"""
    return init().get_part_cadquery(part_name, params=params)


def get_part_build123d(part_name, params=None) -> Part:
    """Get the part from the given project"""
    return init().get_part_build123d(part_name, params=params)


def render(format=None, output_dir=None):
    return init().render(format, output_dir)


def create_package(dst_path=consts.DEFAULT_PACKAGE_CONFIG, config_options={"private": False}):
    yaml = ruamel.YAML()
    private = config_options["private"]
    if private:
        template_name = "init-private.yaml"
    else:
        template_name = "init-public.yaml"
    src_path = os.path.join(os.path.dirname(__file__), "template", template_name)

    with open(src_path) as f:
        config = yaml.load(f)
    for key, value in config_options.items():
        key = ''.join(x.capitalize() if i != 0 else x for i, x in enumerate(key.split('_')))
        if value and value != "empty":
            config.insert(0, key, value)

    if os.path.exists(dst_path):
        pc_logging.error("File already exists: %s" % dst_path)
        return False
    with open(dst_path, "w") as f:
        yaml.dump(config, f)

    return True
