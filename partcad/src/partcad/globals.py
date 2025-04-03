#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko
# Created: 2024-01-20
#
# Licensed under Apache License, Version 2.0.

import os
import threading
import ruamel.yaml as ruamel

from .context import Context
from .assembly import Assembly
from .assembly_factory_assy import AssemblyFactoryAssy
from .assembly_factory_alias import AssemblyFactoryAlias
from .file_factory_url import FileFactoryUrl
from .plugin_factory_provider_manufacturer import PluginFactoryProviderManufacturer
from .plugin_factory_provider_store import PluginFactoryProviderStore
from .plugin_factory_provider_enrich import PluginFactoryProviderEnrich
from .plugin_factory_repository import PluginFactoryRepository
from .plugin_factory_repository_basic import PluginFactoryRepositoryBasic

# from .plugin_factory_repository_tree import PluginFactoryRepositoryTree
# from .plugin_factory_repository_full import PluginFactoryRepositoryFull
from .plugin_factory_repository_enrich import PluginFactoryRepositoryEnrich
from .part_factory_ai_cadquery import PartFactoryAiCadquery
from .part_factory_ai_build123d import PartFactoryAiBuild123d
from .part_factory_ai_openscad import PartFactoryAiScad
from .part_factory_cadquery import PartFactoryCadquery
from .part_factory_build123d import PartFactoryBuild123d
from .part_factory_step import PartFactoryStep
from .part_factory_brep import PartFactoryBrep
from .part_factory_stl import PartFactoryStl
from .part_factory_3mf import PartFactory3mf
from .part_factory_obj import PartFactoryObj
from .part_factory_scad import PartFactoryScad
from .part_factory_kicad import PartFactoryKicad
from .part_factory_extrude import PartFactoryExtrude
from .part_factory_sweep import PartFactorySweep
from .part_factory_alias import PartFactoryAlias
from .part_factory_enrich import PartFactoryEnrich
from .sketch_factory_basic import SketchFactoryBasic
from .sketch_factory_cadquery import SketchFactoryCadquery
from .sketch_factory_build123d import SketchFactoryBuild123d
from .sketch_factory_dxf import SketchFactoryDxf
from .sketch_factory_svg import SketchFactorySvg
from .sketch_factory_alias import SketchFactoryAlias
from .sketch_factory_enrich import SketchFactoryEnrich

from .part import Part
from . import consts
from . import factory
from .user_config import UserConfig
from . import logging as pc_logging

__version__: str = "0.7.127"

global _partcad_context
_partcad_context = None
_partcad_context_lock = threading.Lock()

factory.register("sketch", "basic", SketchFactoryBasic)
factory.register("sketch", "cadquery", SketchFactoryCadquery)
factory.register("sketch", "build123d", SketchFactoryBuild123d)
factory.register("sketch", "dxf", SketchFactoryDxf)
factory.register("sketch", "svg", SketchFactorySvg)
factory.register("sketch", "alias", SketchFactoryAlias)
factory.register("sketch", "enrich", SketchFactoryEnrich)
factory.register("part", "ai-cadquery", PartFactoryAiCadquery)
factory.register("part", "ai-build123d", PartFactoryAiBuild123d)
factory.register("part", "ai-openscad", PartFactoryAiScad)
factory.register("part", "cadquery", PartFactoryCadquery)
factory.register("part", "build123d", PartFactoryBuild123d)
factory.register("part", "step", PartFactoryStep)
factory.register("part", "brep", PartFactoryBrep)
factory.register("part", "stl", PartFactoryStl)
factory.register("part", "3mf", PartFactory3mf)
factory.register("part", "obj", PartFactoryObj)
factory.register("part", "scad", PartFactoryScad)
factory.register("part", "kicad", PartFactoryKicad)
factory.register("part", "extrude", PartFactoryExtrude)
factory.register("part", "sweep", PartFactorySweep)
factory.register("part", "alias", PartFactoryAlias)
factory.register("part", "enrich", PartFactoryEnrich)
factory.register("assembly", "assy", AssemblyFactoryAssy)
factory.register("assembly", "alias", AssemblyFactoryAlias)
factory.register("file", "url", FileFactoryUrl)
factory.register("provider", "manufacturer", PluginFactoryProviderManufacturer)
factory.register("provider", "enrich", PluginFactoryProviderEnrich)
factory.register("provider", "store", PluginFactoryProviderStore)
factory.register("repository", "basic", PluginFactoryRepositoryBasic)
# factory.register("repository", "tree", PluginFactoryRepositoryTree)
# factory.register("repository", "full", PluginFactoryRepositoryFull)
factory.register("repository", "enrich", PluginFactoryRepositoryEnrich)


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
        key = "".join(x.capitalize() if i != 0 else x for i, x in enumerate(key.split("_")))
        if value and value != "empty":
            config.insert(0, key, value)

    if os.path.exists(dst_path):
        pc_logging.error("File already exists: %s" % dst_path)
        return False
    with open(dst_path, "w") as f:
        yaml.dump(config, f)

    return True
