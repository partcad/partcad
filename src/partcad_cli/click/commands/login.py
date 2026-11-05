#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
"""'pc login': sign in to what a plugin is a client of, and keep the credentials."""

import rich_click as click

from ..service import run


@click.command(help="""Sign in to what a plugin is a client of, and keep the credentials.

    PLUGIN is a repository or a provider, as '<package>:<name>'
    ('//pub/universe/thingiverse:thingiverse_repo'). Its 'login' checks the
    credentials it has and, when the site no longer takes them, opens your
    default browser - in a profile of PartCAD's own, with PartCAD's extension in
    it - on the site's sign-in. Sign in there; the extension picks up what that
    leaves behind and closes the window.

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
def cli(cli_ctx, plugin: str, check: bool, manual: bool, browser_name: str, timeout: int) -> None:
    # The browser, the listener and the configuration file are this machine's,
    # so they are here; the plugin runs where every plugin runs, on the daemon
    # (see "Command boundary" in src/partcad_cli/AGENTS.md).
    from partcad_client import browser as pc_browser
    from partcad_client import login as pc_login
    from partcad_utils.user_config import save_parameter_overrides

    def ask(results, interactive):
        return run(
            cli_ctx,
            "plugin.login",
            {"plugin": plugin, "browser": results, "interactive": interactive},
            needs_context=True,
        )

    chosen = None
    if not manual and not check:
        chosen = pc_browser.choose(browser_name)
        if chosen is None:
            click.echo("No browser PartCAD can put its extension in was found; signing in by hand instead.")

    def open_browser(url, spec):
        if chosen is None:
            return None
        opened = pc_browser.open_browser(url, chosen)
        if opened.note:
            click.echo("%s: %s" % (chosen.name, opened.note))
        return opened

    try:
        answer = pc_login.login(
            ask, open_browser, click.echo, interactive=not check, manual=manual or chosen is None, timeout=timeout
        )
    except (RuntimeError, pc_login.LoginCancelled, pc_login.LoginTimedOut) as e:
        raise click.ClickException(str(e))

    parameters = answer.get("parameters") or {}
    if parameters and not check:
        path = save_parameter_overrides(answer["plugin"], parameters)
        click.echo("Saved the credentials of %s in %s." % (answer["plugin"], path))
    if answer.get("message"):
        click.echo(answer["message"])
