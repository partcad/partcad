---
name: install
description: Install PartCAD (the `pc`/`partcad` command) so other skills can run it — either the standalone PyInstaller build from GitHub releases (`executable`) or the partcad-cli module into the active Python environment (`python-module`). Use when the user runs /pc:install or when PartCAD is not installed.
---

# pc:install

Install PartCAD so `pc` and `partcad` become runnable. The argument selects how.
It is in `$ARGUMENTS`; if empty or unrecognized, default to `executable` and say
so.

| Argument | Installs | Afterward it runs as |
| --- | --- | --- |
| `executable` | Standalone PyInstaller bundle from the latest GitHub release (no Python needed) | `pc` / `partcad` on `PATH` |
| `python-module` | The `partcad` wheel into the **active** Python environment | `python -m partcad_cli.click.command` |

## 0. Skip if already installed

Check whether PartCAD is already available, using the same resolution `/pc:init`
uses; if so, report it and stop unless the user asked to reinstall:

```sh
command -v pc || command -v partcad || python -c "import partcad_cli" 2>/dev/null && echo "already installed"
```

## `executable` — standalone build from GitHub releases

Defer to PartCAD's official POSIX installer, which finds the latest release,
downloads the bundle for this OS/arch, verifies the checksum, and links `pc` /
`partcad` into `~/.local/bin`:

```sh
curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh | sh
```

Options pass through the pipe with `sh -s --` (for example
`... | sh -s -- --version 0.7.135`); the same knobs exist as environment
variables (`PARTCAD_VERSION`, `PARTCAD_REPOSITORY`, `PARTCAD_BIN_DIR`, …).

**There is no published standalone release yet.** Today the installer ends with a
download 404:

```
error: download failed.
       There may be no build of <version> for <platform>.
```

(or *"could not determine the latest release"* if there is no release at all).
When the standalone bundle is not published, report that **no published PartCAD
installer is available** and stop. Do not fall back to another install method and
do not hand-roll one.

## `python-module` — into the active Python environment

Only when the user explicitly asks for this mode. Install the `partcad` wheel
with the current interpreter's pip (use `python3` if `python` is absent or
Python 2). It carries the CLI, the JSON-RPC service and the viewer client, so
this one install is everything:

```sh
python -m pip install -U partcad
```

If pip refuses on a permissions or externally-managed-environment error, retry
with `--user`, or use `pipx install partcad` or a virtualenv. Verify and
report the result, then suggest re-running the original task (for example
`/pc:init`):

```sh
python -m partcad_cli.click.command --version
```
