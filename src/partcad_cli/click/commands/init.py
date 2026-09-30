#
# PartCAD, 2025
# OpenVMP, 2023
#
# Author: Roman Kuzmenko, Aleksandr Ilin
# Created: 2023-12-23
#
# Licensed under Apache License, Version 2.0.
#

import os

import rich_click as click
from packaging.specifiers import InvalidSpecifier, SpecifierSet

import partcad as pc

from ..cli_context import CliContext


class DynamicPromptOption(click.Option):
    def prompt_for_value(self, ctx):
        interactive = ctx.params.get("interactive")
        if not interactive:
            return self.default
        if self.type is click.STRING:
            suffix = f" [default: {self.default if self.default else 'empty'}] : "
            user_ipt = input(self.prompt + suffix)
            if user_ipt:
                return user_ipt
        elif self.type is click.BOOL:
            suffix = f" (y/N) [default: {'n/N' if not self.default else 'y/Y'}] : "
            user_ipt = input(self.prompt + suffix)
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
    default=f">={pc.__version__}",
    cls=DynamicPromptOption,
    help="Required PartCAD version spec string",
    prompt="Enter the required PartCAD version spec string",
    show_envvar=True,
)
@click.option(
    "--skills/--no-skills",
    "skills",
    is_flag=True,
    default=True,
    show_envvar=True,
    help="Install the PartCAD AI agent skills into this repository",
)
@click.option(
    "--skills-only",
    is_flag=True,
    default=False,
    show_envvar=True,
    help="Install the AI agent skills only, leaving any package alone",
)
@click.option(
    "--agents",
    type=str,
    default="all",
    show_default=True,
    show_envvar=True,
    help="Which agents to install the skills for: 'all', or a comma-separated list (claude, cursor)",
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
@click.pass_obj
def cli(cli_ctx: CliContext, click_ctx: click.rich_context.RichContext, **kwargs):
    with pc.telemetry.set_context(cli_ctx.otel_context):
        # ctx: pc.Context = cli_ctx.get_partcad_context()

        if click_ctx.parent.params.get("package") is not None:
            if os.path.isdir(click_ctx.parent.params.get("package")):
                dst_path = os.path.join(click_ctx.parent.params.get("package"), "partcad.yaml")
            else:
                dst_path = click_ctx.parent.params.get("package")
        else:
            dst_path = "partcad.yaml"

        # None of these is part of the package configuration: "interactive"
        # decided how the options above were collected, and the other two are
        # about the repository around the package rather than the package.
        install_skills = kwargs.pop("skills")
        skills_only = kwargs.pop("skills_only")
        # "all" rather than a literal list, so that an agent added to
        # "partcad.ai_agents.AGENTS" is installed for without touching the CLI.
        agents = kwargs.pop("agents")
        agents = None if agents.strip() == "all" else [a.strip() for a in agents.split(",") if a.strip()]

        if skills_only:
            # The whole command, for a repository that has a package already --
            # which is the common case for this, since the skills are installed
            # by the "pc init" that created it. Nothing is written to
            # "partcad.yaml", so an existing one is neither read nor replaced,
            # and the package need not exist at all.
            if not install_skills:
                pc.logging.error("'--skills-only' and '--no-skills' ask for opposite things")
                return
            if not pc.install_agent_skills(os.path.dirname(os.path.abspath(dst_path)), agents):
                # An error here, unlike below: installing them is the whole of
                # what was asked for, so there is nothing left that succeeded.
                pc.logging.error("Failed installing the AI agent skills!")
            return

        if kwargs.get("interactive"):
            pc.logging.info("Validating package configuration...")
            for key in kwargs:
                if isinstance(kwargs[key], str) and "default: " in kwargs[key]:
                    kwargs[key] = kwargs[key].replace("default: ", "")
                value = kwargs[key]
                if value is not None and key.endswith("version"):
                    try:
                        SpecifierSet(value)
                    except InvalidSpecifier:
                        pc.logging.error(f"'{value}' is not a valid version string")
                if key == "name" and value is not None and not value.startswith(pc.ROOT):
                    kwargs[key] = f"{pc.ROOT}{value}"

            if pc.logging.had_errors:
                pc.logging.error(f"Failed creating '{dst_path}'!")
                return

        pc.logging.info(f"Creating package configuration at '{dst_path}'...")
        # "interactive" decided how the options above were collected; it is not
        # part of the package configuration either.
        config_options = {key: value for key, value in kwargs.items() if key != "interactive"}
        if pc.create_package(dst_path, config_options):
            pc.logging.info(f"Successfully created package at '{dst_path}'")
            # A button to press next to the package that was just created: the
            # "Render" command, in the launch configuration of the repository
            # this was run in. It reports what it did, and a failure to add it
            # is not a failure to create the package.
            package_dir = os.path.dirname(os.path.abspath(dst_path))
            pc.add_render_configuration(package_dir)
            # And what the agent in the editor needs to press it: the skills
            # that teach it to drive PartCAD, for Claude Code and for Cursor.
            # Reported the same way, and a failure to install them is not a
            # failure to create the package either.
            if install_skills:
                pc.install_agent_skills(package_dir, agents)
        else:
            pc.logging.error(f"Failed creating '{dst_path}'!")
