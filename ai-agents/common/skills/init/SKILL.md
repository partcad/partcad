---
name: init
description: Initialize a PartCAD package in the current directory by running the installed PartCAD CLI (`pc init` / `partcad init`). Use when the user runs /pc:init or asks to initialize or create a PartCAD package or project.
---

# pc:init

Initialize a PartCAD package in the current directory by delegating to the
installed PartCAD command-line tool. Do **not** hand-write `partcad.yaml`
yourself — run the real CLI so the result always matches the installed version.

## 1. Locate the PartCAD command

Find a usable invocation, most-preferred first, and remember it as `PARTCAD`.
This covers a `pc`/`partcad` on `PATH` (a wheel install or the standalone
bundle), and a `partcad-cli` that is importable in the current Python
environment but whose console scripts are not on `PATH`:

```sh
if   command -v pc      >/dev/null 2>&1;         then PARTCAD="pc"
elif command -v partcad >/dev/null 2>&1;         then PARTCAD="partcad"
elif python  -c "import partcad_cli" >/dev/null 2>&1; then PARTCAD="python -m partcad_cli.click.command"
elif python3 -c "import partcad_cli" >/dev/null 2>&1; then PARTCAD="python3 -m partcad_cli.click.command"
else PARTCAD=""; fi
echo "PARTCAD=${PARTCAD:-<none>}"
```

## 2. If nothing is installed

If `PARTCAD` is empty, PartCAD is not available. Stop and tell the user to
install it first — do not fabricate a `partcad.yaml`:

> PartCAD is not installed. Run `/pc:install executable` for the standalone
> build, or `/pc:install python-module` to install it into the current Python
> environment, then re-run `/pc:init`.

## 3. Run init

Otherwise run PartCAD's own `init`, forwarding anything the user typed after the
command (available as `$ARGUMENTS`):

```sh
$PARTCAD init $ARGUMENTS
```

If the user asked for options you are unsure about, run `$PARTCAD init --help`
first. Report what the command created (typically `partcad.yaml`), and if it
prints an error, surface that error verbatim rather than working around it.
