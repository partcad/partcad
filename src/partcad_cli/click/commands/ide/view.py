#
# PartCAD, 2025
#
# Licensed under Apache License, Version 2.0.
#

import functools

import rich_click as click

from partcad_ide_client.protocol import VIEWER_TABS

from ...service import run

# What each tab is called on the command line, where it differs from its id:
# 'supply' is the tab the viewer labels "Buy", and the flag says what the tab
# says.
_FLAG_NAMES = {"supply": "buy"}

_TAB_HELP = {
    "3d": "the 3D view",
    "2d": "the 2D tab: the object rendered to a picture",
    "draft": "the Draft tab: a dimensioned drawing",
    "fea": "the FEA tab, which runs the part's structural analysis",
    "cfd": "the CFD tab, which runs the part's flow analysis",
    "bvb": "the Build vs Buy tab",
    "build": "the Build tab: how what is built is made",
    "supply": "the Buy tab: where to buy what is bought",
    "bom": "the Bill of Materials tab",
    "assembly": "the Assembly tab: the assembly instructions",
}


def _tab_flags():
    """'--design-3d', '--analysis-fea', ... : one flag per viewer tab, as '<group>-<tab>'.

    Generated from 'partcad_ide_client.protocol.VIEWER_TABS', so a tab added to
    the viewer is a flag here without anybody writing one. Each is a flag of its
    own rather than a value of one option so that the command reads the way the
    viewer does (a group, then a tab), and they are refused in pairs below,
    because a viewer is on one tab.
    """
    flags = []
    for group, tabs in VIEWER_TABS.items():
        for tab in tabs:
            flags.append(("%s-%s" % (group, _FLAG_NAMES.get(tab, tab)), tab))
    return flags


def tab_options(command):
    """Add the tab flags to 'command', which is then called with 'tab' (an id, or None) in their place."""
    flags = _tab_flags()

    @functools.wraps(command)
    def wrapper(*args, **kwargs):
        chosen = [(flag, tab) for flag, tab in flags if kwargs.pop("tab_" + tab.replace("-", "_"), False)]
        if len(chosen) > 1:
            raise click.UsageError(
                "The PartCAD Viewer shows one tab at a time; pass one of %s."
                % ", ".join("--" + flag for flag, _ in chosen)
            )
        kwargs["tab"] = chosen[0][1] if chosen else None
        return command(*args, **kwargs)

    for flag, tab in reversed(flags):
        wrapper = click.option(
            "--" + flag,
            "tab_" + tab.replace("-", "_"),
            is_flag=True,
            help="Open the viewer on %s" % _TAB_HELP.get(tab, "the '%s' tab" % tab),
        )(wrapper)
    return wrapper


# TODO-98: @clairbee: fix type checking here
# TODO: @alexanderilyin: https://stackoverflow.com/a/37491504/25671117
@click.command(help="View a part, assembly, or scene visually")
@click.option(
    "-V",
    "--verbal",
    "verbal",
    is_flag=True,
    help="Produce a verbal output instead of a visual one",
    show_envvar=True,
)
@click.option(
    "-P",
    "--package",
    "package",
    type=str,
    help="Package to retrieve the object from",
    default=None,
    show_envvar=True,
)
@click.option(
    "-s",
    "--sketch",
    help="The object is a sketch",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-i",
    "--interface",
    help="The object is an interface",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-a",
    "--assembly",
    help="The object is an assembly",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-S",
    "--scene",
    help="The object is a scene",
    is_flag=True,
    show_envvar=True,
)
@click.option(
    "-p",
    "--param",
    "params",
    multiple=True,
    metavar="<param_name>=<param_value>",
    help="Assign a value to the parameter",
    show_envvar=True,
)
@tab_options
@click.argument("object", type=str, required=False)  # help="Part (default), assembly or scene to test"
@click.pass_context
@click.pass_obj
def cli(cli_ctx, context, verbal, package, interface, assembly, sketch, scene, params, object, tab):
    if tab is not None and verbal:
        raise click.UsageError("--verbal shows nothing in the viewer, so it opens no tab of it.")
    rpc_params = {
        "verbal": verbal,
        "interface": interface,
        "assembly": assembly,
        "sketch": sketch,
        "scene": scene,
        "params": list(params),
        "object": object,
    }
    if package is not None:
        rpc_params["package"] = package
    if tab is not None:
        # Only when asked for: a daemon from before the flags has no use for
        # the key, and every show without one leaves the viewer where it is.
        rpc_params["tab"] = tab

    result = run(cli_ctx, "inspect.object", rpc_params, span_name="inspect", needs_context=True)

    # The root's '--quiet', read off the root: this command is two levels down
    # ('pc ide view'), so its parent is the 'ide' group, which has no such
    # option. ('context' is click's here and 'cli_ctx' PartCAD's -- the two
    # decorators apply bottom-up.) It used to read a parameter named "q", which
    # does not exist either, so '-q' never silenced the summary.
    if verbal and result and result.get("summary") is not None:
        if not context.find_root().params.get("quiet"):
            print("%s" % result["summary"])
