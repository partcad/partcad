#
# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksandr Ilin
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#
import rich_click as click
import os, sys
from packaging.specifiers import SpecifierSet, InvalidSpecifier

import partcad.logging as logging
from partcad.globals import create_package
from partcad.consts import ROOT
from partcad import __version__ as pc_version


class DynamicPromptOption(click.Option):
    def prompt_for_value(self, ctx):
        interactive = ctx.params.get("interactive")
        if not interactive:
            return self.default
        if self.type is click.STRING:
            suffix = f" [default: {self.default if self.default else 'empty'}] : "
            user_ipt = input(self.prompt+suffix)
            if user_ipt:
                return user_ipt
        elif self.type is click.BOOL:
            suffix = f" (y/N) [default: {'n/N' if not self.default else 'y/Y'}] : "
            user_ipt = input(self.prompt+suffix)
            if user_ipt:
                return user_ipt.lower() in ["y", "yes"]
        return self.default

@click.command(help="Create a new PartCAD package in the current directory")
@click.option(
    "-i",
    "--interactive",
    is_flag=True,
    default=False,
    show_envvar=True,
    help="Enable interactive mode",
)
@click.option(
    "-n",
    "--name",
    type=str,
    cls=DynamicPromptOption,
    help="The assumed package path for standalone development(for advanced users)",
    prompt="Enter package name",
    show_envvar=True,
)
@click.option(
    "-d",
    "--desc",
    type=str,
    cls=DynamicPromptOption,
    help="Short description of the package",
    prompt="Enter a short description of the package",
    show_envvar=True,
)
@click.option(
    "-mnf",
    "--manufacturable",
    is_flag=True,
    default=False,
    cls=DynamicPromptOption,
    help="Whether or not the objects in this package are manufacturable",
    prompt="Are the objects in this package manufacturable?",
    show_envvar=True,
)
@click.option(
    "-u",
    "--url",
    type=str,
    cls=DynamicPromptOption,
    help="The package or maintainer's url",
    prompt="Enter the package or maintainer's URL",
    show_envvar=True,
)
@click.option(
    "-P",
    "--poc",
    type=str,
    cls=DynamicPromptOption,
    help="Point of contact, maintainer's email",
    prompt="Enter point of contact (maintainer's email)",
    show_envvar=True,
)
@click.option(
    "-pv",
    "--partcad",
    type=str,
    default=f">={pc_version}",
    cls=DynamicPromptOption,
    help="Required PartCAD version spec string",
    prompt="Enter the required PartCAD version spec string",
    show_envvar=True,
)
@click.option(
    "-pyv",
    "--python-version",
    type=str,
    default=f'>={".".join(map(str, list(sys.version_info)[:2]))}',
    cls=DynamicPromptOption,
    help="Python version for sandboxing if applicable",
    prompt="Enter the python version for sandboxing (if applicable)",
    show_envvar=True,
)
@click.option(
    "-p",
    "--private",
    is_flag=True,
    default=False,
    cls=DynamicPromptOption,
    help="Initialize this package as private",
    prompt="Do you want this package to be private?",
    show_envvar=True,
)
@click.pass_context
def cli(ctx: click.rich_context.RichContext, **kwargs):
    if not ctx.parent.params.get("package") is None:
        if os.path.isdir(ctx.parent.params.get("package")):
            dst_path = os.path.join(ctx.parent.params.get("package"), "partcad.yaml")
        else:
            dst_path = ctx.parent.params.get("package")
    else:
        dst_path = "partcad.yaml"

    if kwargs.get("interactive"):
        logging.info("Validating package configuration...")
        for key in kwargs:
            if isinstance(kwargs[key], str) and "default: " in kwargs[key]:
                kwargs[key] = kwargs[key].replace("default: ", "")
            value = kwargs[key]
            if value is not None and key.endswith("version"):
                try:
                    SpecifierSet(value)
                except InvalidSpecifier:
                    logging.error(f"'{value}' is not a valid version string")
            if key == "name" and value is not None and not value.startswith(ROOT):
                kwargs[key] = f"{ROOT}{value}"

        if logging.had_errors:
            logging.error(f"Failed creating '{dst_path}'!")
            return

    logging.info(f"Creating package configuration at '{dst_path}'...")
    config_options = {key: value for key, value in kwargs.items() if key != "interactive"}
    if create_package(dst_path, config_options):
        logging.info(f"Successfully created package at '{dst_path}'")
    else:
        logging.error(f"Failed creating '{dst_path}'!")
