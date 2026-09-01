---
name: setup
description: Set PartCAD up on this machine so other skills can run it — the `pc`/`partcad` command line tools, either as the standalone build from GitHub releases (`executable`) or as the wheel in the active Python environment (`python-module`), plus the PartCAD extension when this session runs inside Visual Studio Code or VSCodium. Use when the user runs /pc:setup or when PartCAD is not installed.
---

# pc:setup

Set PartCAD up so `pc` and `partcad` become runnable, and so the editor this
session is running in — if it is running in one — can browse and view what they
build.

> Named `setup` rather than `install` because `pc install` is a different thing
> entirely. That command is PartCAD's `npm install`: it fetches a *package's*
> imports into the local cache, and it needs PartCAD to already be here. This
> skill is what puts PartCAD here.

Two parts, in order:

1. **The command line tools**, always. The argument selects how. It is in
   `$ARGUMENTS`; if empty or unrecognized, default to `executable` and say so.
2. **The editor extension**, only when this session is running inside Visual
   Studio Code or VSCodium. Everywhere else there is nothing to do.

| Argument | Installs | Afterward it runs as |
| --- | --- | --- |
| `executable` | Standalone PyInstaller bundle from the latest GitHub release (no Python needed) | `pc` / `partcad` on `PATH` |
| `python-module` | The `partcad` wheel into the **active** Python environment | `python -m partcad_cli.click.command` |

## Which version

The plugin these skills ship in is released by PartCAD's own release, under
PartCAD's own version: the `version` in the plugin's `.claude-plugin/plugin.json`
names the release they were written against. Installing the newest release is
the default and is normally right — the skills use documented commands, which do
not disappear. Install that exact one when a newer PartCAD turns out to behave
differently from what a skill describes, and say why. How to pin depends on the
mode, and the two do not share a knob:

| Mode | Pin the plugin's version with |
| --- | --- |
| `executable` | `... \| sh -s -- --version <version>`, or `PARTCAD_VERSION=<version>` |
| `python-module` | `python -m pip install -U "partcad==<version>"` |

`--version` and `PARTCAD_VERSION` are `install.sh` options and do nothing in
`python-module` mode, where the version is part of the requirement `pip` is
given.

## 0. Skip if already installed

Check whether PartCAD is already available, using the same resolution `/pc:init`
uses; if so, report it and go on to *The editor extension* below — do not
reinstall unless the user asked for it:

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

Every release publishes bundles for Linux (x86_64, arm64), macOS (Apple silicon)
and Windows, along with a `platforms.json` manifest the installer reads to pick
the right one for this machine. The download is around 57MB on Linux x86_64 and
about half that on macOS and Linux arm64.

Should the installer fail, report what it said and stop. Do not fall back to
another install method and do not hand-roll one. The two failures worth
recognizing:

```
error: download failed.
       There may be no build of <version> for <platform>.
```

— no bundle for this platform in the release that was asked for. `--platform`
names one explicitly; `--version` picks a different release.

```
error: could not determine the latest release
```

— the release list could not be reached at all, which is a network or rate-limit
problem rather than a missing build.

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
report the result:

```sh
python -m partcad_cli.click.command --version
```

## The editor extension

Do this after the command line tools are in place, whichever mode installed
them. The PartCAD extension puts a package's parts, assemblies and sketches in
the sidebar and hosts the `PartCAD Viewer`; it is a JSON-RPC client of the
`partcad-json-rpc` those tools just provided, so it is worth having wherever
this session is running in an editor that can host it.

Outside such an editor there is nothing to install and nothing to report. Do not
go looking for an editor elsewhere on the machine, and do not offer to install
one.

### 1. Which editor, if any

Visual Studio Code, VSCodium and the PartCAD IDE all set `TERM_PROGRAM=vscode`
in their integrated terminals, and each one puts *its own* command line tool on
the `PATH` of those terminals. That pair is what tells them apart:

```sh
EDITOR_CLI=""
if [ "${TERM_PROGRAM:-}" = "vscode" ]; then
  # The built-in Git extension names the executable of the window this terminal
  # belongs to. Complete by construction: anything in this family that is
  # neither the PartCAD IDE nor VSCodium is Visual Studio Code, so there is no
  # list of VS Code paths to keep up to date and nothing falls through a gap.
  case "${VSCODE_GIT_ASKPASS_NODE:-}" in
    "")                     EDITOR_CLI="" ;;
    *partcad-ide*)          EDITOR_CLI="partcad-ide" ;;
    *odium*|*Odium*)        EDITOR_CLI="codium" ;;
    *insiders*|*Insiders*)  EDITOR_CLI="code-insiders" ;;
    *)                      EDITOR_CLI="code" ;;
  esac
  # Unset (the Git extension can be disabled), or naming a build whose command
  # line tool is not installed: take the first of these on `PATH`, left to
  # right. The integrated terminal puts the running application's own `bin`
  # directory at the front, so the leftmost match is that application -- which
  # is why the order of `PATH` decides and not the order of this list. A fixed
  # candidate order answers with whichever editor is listed first rather than
  # whichever one is running, on any machine that has two of them.
  if [ -z "${EDITOR_CLI}" ] || ! command -v "${EDITOR_CLI}" >/dev/null 2>&1; then
    EDITOR_CLI=""
    IFS=:
    for dir in ${PATH}; do
      for candidate in partcad-ide codium codium-insiders code code-insiders; do
        if [ -x "${dir}/${candidate}" ]; then EDITOR_CLI="${candidate}"; break 2; fi
      done
    done
    unset IFS
  fi
fi
echo "EDITOR_CLI=${EDITOR_CLI:-<none>}"
```

An empty `EDITOR_CLI` means a plain terminal, or an editor whose command line
tool is not on `PATH` (on macOS, "Shell Command: Install 'code' command in PATH"
from the command palette adds it). Say nothing about extensions and stop.

### 2. Stop if there is nothing to do

`partcad-ide` is the **PartCAD IDE**, which already carries this extension
inside the application and versions it with the IDE — a new one arrives with a
new IDE, not from here. Report that and stop.

Otherwise, check whether it is installed already, by its extension id:

```sh
"${EDITOR_CLI}" --list-extensions | grep -qix "openvmp.partcad" && echo "already installed"
```

### 3. Install it

Use `${EDITOR_CLI}` rather than a literal name in both of these: it is what
distinguishes an Insiders build from a stable one, and installing into the wrong
one leaves the window the user is looking at without the extension.

**Visual Studio Code** (`code`, `code-insiders`) installs it from the Visual
Studio Marketplace by id:

```sh
"${EDITOR_CLI}" --install-extension OpenVMP.partcad
```

**VSCodium** (`codium`, `codium-insiders`) does not, and must not: its gallery
is [Open VSX](https://open-vsx.org/), where PartCAD does not publish, and the
Visual Studio Marketplace's terms restrict its use to Microsoft's own products.
Install the `.vsix` from the GitHub release instead — the same package, and one
build serves every platform because the extension is a JSON-RPC client with no
Python and nothing compiled in it:

```sh
version="$(curl -fsSL https://api.github.com/repos/partcad/partcad/releases/latest |
  sed -n 's/.*"tag_name" *: *"\([^"]*\)".*/\1/p' | head -n 1)"
if [ -z "${version}" ]; then
  echo "error: could not determine the latest release" >&2
else
  vsix="$(mktemp -d)/partcad-${version}.vsix"
  curl -fsSL -o "${vsix}" \
    "https://github.com/partcad/partcad/releases/download/${version}/partcad-${version}.vsix" &&
    "${EDITOR_CLI}" --install-extension "${vsix}"
fi
```

Name a release in place of `${version}` to pin one, the same way `--version`
pins the tools above. If either step fails, report what it said and stop — these
are the same two failures `install.sh` names, a release that cannot be resolved
and an asset that cannot be downloaded, and neither is a reason to reach for the
Marketplace.

### 4. Report

The extension loads on the next window reload, so say so: "Developer: Reload
Window" from the command palette, or reopen the folder.

It then finds the tools by itself — an existing standalone installation, or a
`partcad-json-rpc` on `PATH` — and only asks when it finds neither. Two cases
where it will find neither, worth mentioning when they apply:

- **`python-module` into a virtual environment.** The `PATH` the extension
  searches is the one the editor was *started* with, which does not include a
  virtualenv unless the editor was launched from it. Point
  `partcad.servicePath` at the environment's `partcad-json-rpc`, or use "Find
  installed PartCAD", which fills that setting in.
- **`executable` in a session whose `PATH` the editor never saw.** Reloading
  the window is enough if `~/.local/bin` is on the editor's `PATH`; otherwise
  the same setting is the answer.

## Finally

Whatever was set up, close by suggesting the task the user was actually after —
`/pc:init` to start a package, `/pc:gen` to make something — rather than leaving
them at a bare installation.
