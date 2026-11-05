#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc login': sign in to what a plugin is a client of, and keep the credentials."""

import rich_click as click

from ..service import run

# What 'pc login --agent' exits with when it printed what to do: not logged in,
# and not failed either - a person has something to do first.
INSTRUCTIONS_EXIT_CODE = 3


@click.command(help="""Sign in to what a plugin is a client of, and keep the credentials.

    PLUGIN is a repository or a provider, as '<package>:<name>'
    ('//pub/universe/thingiverse:thingiverse_repo'). Its 'login' checks the
    credentials it has and, when the site no longer takes them, opens your
    default browser - in a profile of PartCAD's own, with PartCAD's extension in
    it - on the site's sign-in. Sign in there; the extension picks up what that
    leaves behind and closes the window. A default browser the extension cannot
    go into is passed over for an installed one it can.

    With --agent (or --non-interactive), for an AI agent or a script with
    nobody at the screen, no browser is opened: what a person would do there
    is printed instead - where to sign in, what to copy, any other way in the
    plugin knows of - and the command exits with status 3. What was found is
    handed over with --set NAME=VALUE, in either mode, and checked with the
    site like what a browser brings. 'pc mcp' logs in this way.

    The credentials are saved in your PartCAD configuration file
    (~/.partcad/config.yaml) as your overrides of the plugin's parameters, which
    is how every later command hands them to the plugin. The file is made
    readable by you only.""")
@click.argument("plugin", type=str)
@click.option(
    "--check",
    is_flag=True,
    help="Only check the credentials the plugin has; never open the browser. Exits non-zero if they do not work",
)
@click.option(
    "--interactive",
    "interactive",
    flag_value=True,
    default=True,
    help="Somebody is at the screen: open a browser for them to sign in (the default)",
)
@click.option(
    "--agent",
    "--non-interactive",
    "interactive",
    flag_value=False,
    help="Nobody is at the screen: print what a person would do in the browser, and how to hand it over, "
    "instead of opening one. Exits with status 3 when it did",
)
@click.option(
    "--set",
    "assignments",
    multiple=True,
    metavar="NAME=VALUE",
    help="A value the plugin would otherwise have a browser find - a token, an API key - by the name "
    "--agent prints. Repeat for each",
)
@click.option(
    "--manual",
    is_flag=True,
    help="Do not open a browser: print the address of a page to enter what the site gives you by hand",
)
@click.option(
    "--browser",
    "browser_name",
    type=str,
    envvar="PC_LOGIN_BROWSER",
    help="The browser to sign in with: a path, a command, or chrome, edge, brave, chromium or firefox. "
    "Defaults to your default browser",
    show_envvar=True,
)
@click.option(
    "--timeout",
    type=click.IntRange(min=10),
    help="How many seconds to wait for each sign-in in the browser (the plugin says, by default)",
)
@click.pass_obj
def cli(
    cli_ctx,
    plugin: str,
    check: bool,
    interactive: bool,
    assignments: tuple,
    manual: bool,
    browser_name: str,
    timeout: int,
) -> None:
    # The browser, the listener and the configuration file are this machine's,
    # so they are here; the plugin runs where every plugin runs, on the daemon
    # (see "Command boundary" in src/partcad_cli/AGENTS.md).
    from partcad_client import browser as pc_browser
    from partcad_client import login as pc_login
    from partcad_utils.user_config import save_parameter_overrides

    values = {}
    for assignment in assignments:
        name, equals, value = assignment.partition("=")
        if not equals or not name.strip():
            raise click.BadParameter("'%s' is not NAME=VALUE" % assignment, param_hint="--set")
        values[name.strip()] = value
    if manual and not interactive:
        raise click.UsageError("--manual is for a person entering values by hand; --agent has nobody to")

    def ask(results):
        request = {"plugin": plugin, "browser": results, "check": check, "non_interactive": not interactive}
        if values:
            request["values"] = values
        return run(cli_ctx, "plugin.login", request, needs_context=True)

    chosen = None
    if interactive and not manual and not check:
        chosen = pc_browser.choose(browser_name)
        if chosen is None:
            click.echo("No browser PartCAD can put its extension in was found; signing in by hand instead.")

    def open_browser(url, spec):
        if chosen is None:
            return None
        try:
            opened = pc_browser.open_browser(url, chosen)
        except OSError as e:
            # A browser named by path that will not start: the manual page,
            # whose address the loop prints next, still does the job.
            click.echo("Could not start %s (%s); signing in by hand instead." % (chosen.name, e))
            return None
        if opened.note:
            click.echo("%s: %s" % (chosen.name, opened.note))
        return opened

    try:
        answer = pc_login.login(ask, open_browser, click.echo, manual=manual or chosen is None, timeout=timeout)
    except (RuntimeError, pc_login.LoginCancelled, pc_login.LoginTimedOut) as e:
        raise click.ClickException(str(e))

    if answer.get("status") == "instructions":
        name = answer.get("plugin") or plugin

        def hand_over(names):
            return "Hand %s over with:\n  pc login --agent %s %s" % (
                "it" if len(names) == 1 else "them",
                name,
                " ".join("--set %s=<%s>" % (n, n) for n in names),
            )

        click.echo(pc_login.instructions_text(name, answer.get("spec") or {}, hand_over))
        # Not logged in, and not a failure either: something is to be done first.
        click.get_current_context().exit(INSTRUCTIONS_EXIT_CODE)

    parameters = answer.get("parameters") or {}
    if parameters and not check:
        path = save_parameter_overrides(answer["plugin"], parameters)
        click.echo("Saved the credentials of %s in %s." % (answer["plugin"], path))
    if answer.get("message"):
        click.echo(answer["message"])
