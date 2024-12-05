# CLI

## Old command line interface

```
⬢ [Docker] ❯ pc --help
usage: pc [-h] [-v] [-q] [--no-ansi] [-p CONFIG_PATH] {version,add,add-part,add-assembly,init,info,install,update,list,list-all,list-sketches,list-interfaces,list-mates,list-parts,list-assemblies,render,inspect,status,test,supply} ...

PartCAD command line tool

positional arguments:
  {version,add,add-part,add-assembly,init,info,install,update,list,list-all,list-sketches,list-interfaces,list-mates,list-parts,list-assemblies,render,inspect,status,test,supply}
    version             Print PartCAD version and exit
    add                 Import a package
    add-part            Add a part
    add-assembly        Add an assembly
    init                Initialize a new PartCAD package in this directory
    info                Show detailed info on a part, assembly or scene
    install             Download and prepare all imported packages
    update              Update all imported packages
    list                List imported packages
    list-all            List available parts, assemblies and scenes
    list-sketches       List available sketches
    list-interfaces     List available interfaces
    list-mates          List available mating interfaces
    list-parts          List available parts
    list-assemblies     List available assemblies
    render              Render the selected or all parts, assemblies and scenes in this package
    inspect             Visualize a part, assembly or scene
    status              Display the state of internal data used by PartCAD
    test                Render the selected or all parts, assemblies and scenes in this package
    ai                  AI related commands
    supply              Supplier related commands

options:
  -h, --help            show this help message and exit
  -v                    Increase the level of verbosity
  -q                    Decrease the level of verbosity
  --no-ansi             Plain logging output. Do not use colors or animations.
  -p CONFIG_PATH        Package path (a YAML file or a directory with 'partcad.yaml')

took 2s
```

## New command line interface

```
⬢ [Docker] ❯ partcad --help

 Usage: partcad [OPTIONS] COMMAND [ARGS]...


 ██████╗  █████╗ ██████╗ ████████╗ ██████╗ █████╗ ██████╗
 ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
 ██████╔╝███████║██████╔╝   ██║   ██║     ███████║██║  ██║
 ██╔═══╝ ██╔══██║██╔══██╗   ██║   ██║     ██╔══██║██║  ██║
 ██║     ██║  ██║██║  ██║   ██║   ╚██████╗██║  ██║██████╔╝
 ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═════╝

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│            -v                     Increase the level of verbosity                                                    │
│            -q                     Decrease the level of verbosity                                                    │
│ --no-ansi                         Plain logging output. Do not use colors or animations.                             │
│            -p  PATH               Package path (a YAML file or a directory with 'partcad.yaml')                      │
│ --format       [time|path|level]  Log prefix format                                                                  │
│ --help                            Show this message and exit.                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ add                               Import a package, add a part or assembly.                                          │
│ info                              Show detailed info on a part, assembly or scene                                    │
│ init                              Initialize a new PartCAD package in this directory                                 │
│ inspect                           Visualize a part, assembly or scene                                                │
│ install                           Download and prepare all imported packages                                         │
│ list                              List components                                                                    │
│ render                            Render the selected or all parts, assemblies and scenes in this package            │
│ status                            Display the state of internal data used by PartCAD                                 │
│ supply                            Supplier related commands                                                          │
│ test                              Render the selected or all parts, assemblies and scenes in this package            │
│ update                            Update all imported packages                                                       │
│ version                           Print PartCAD & PartCAD CLI versions and exit                                      │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯

took 2s
```

## Checklist

| v0.7.16              | v0.8.0                    | Scenarios @ `features/partcad-cli/` |
| -------------------- | ------------------------- | ----------------------------------- |
| `pc`                 | `partcad`                 | `pc.feature`                        |
| `pc version`         | `partcad version`         | `commands/version.feature`          |
| `pc add`             | `partcad add package`     | `commands/add/package.feature`      |
| `pc add-part`        | `partcad add part`        | `commands/add/part.feature`         |
| `pc add-assembly`    | `partcad add assembly`    | `commands/add/assembly.feature`     |
| `pc init`            | `partcad init`            | `commands/init.feature`             |
| `pc info`            | `partcad info`            | `commands/info.feature`             |
| `pc install`         | `partcad install`         | `commands/install.feature`          |
| `pc update`          | `partcad update`          | `commands/update.feature`           |
| `pc list`            | `partcad list packages`   | `commands/list/packages.feature`    |
| `pc list-all`        | `partcad list all`        | `commands/list/all.feature`         |
| `pc list-sketches`   | `partcad list sketches`   | `commands/list/sketches.feature`    |
| `pc list-interfaces` | `partcad list interfaces` | `commands/list/interfaces.feature`  |
| `pc list-mates`      | `partcad list mates`      | `commands/list/mates.feature`       |
| `pc list-parts`      | `partcad list parts`      | `commands/list/parts.feature`       |
| `pc list-assemblies` | `partcad list assemblies` | `commands/list/assemblies.feature`  |
| `pc render`          | `partcad render`          | `commands/render.feature`           |
| `pc inspect`         | `partcad inspect`         | `commands/inspect.feature`          |
| `pc status`          | `partcad status`          | `commands/status.feature`           |
| `pc test`            | `partcad test`            | `commands/test.feature`             |
| `pc ai regenerate`   | `partcad ai regenerate`   | `commands/ai/regenerate.feature`    |
| `pc supply find`     | `partcad supply find`     | `commands/supply/find.feature`      |
| `pc supply caps`     | `partcad supply caps`     | `commands/supply/caps.feature`      |
| `pc supply quote`    | `partcad supply quote`    | `commands/supply/quote.feature`     |
| `pc supply order`    | `partcad supply order`    | `commands/supply/order.feature`     |

### Steps

| `features/partcad-cli/...`         | Passed | Failed | Undefined | Coverage | `@wip` | `@success` | `@failure` | `@help` |
| ---------------------------------- | ------ | ------ | --------- | -------- | ------ | ---------- | ---------- | ------- |
| `pc.feature`                       | 57     | 0      | 0         | N/A      | 19     |            |            |         |
| `commands/version.feature`         | 8      | 0      | 0         | N/A      | 0      |            |            |         |
| `commands/add/package.feature`     | 19     | 0      | 0         | N/A      | 0      |            |            |         |
| `commands/add/part.feature`        | 0      | 0      | 0         | N/A      | 185    |            |            |         |
| `commands/add/assembly.feature`    | 0      | 0      | 0         | N/A      | 30     |            |            |         |
| `commands/init.feature`            | 22     | 0      | 0         | N/A      | 20     |            |            |         |
| `commands/info.feature`            | 0      | 0      | 0         | N/A      | 30     |            |            |         |
| `commands/install.feature`         | 7      | 0      | 0         | N/A      | 25     |            |            |         |
| `commands/update.feature`          | 9      | 0      | 0         | N/A      | 0      |            |            |         |
| `commands/list/packages.feature`   | 15     | 0      | 4         | N/A      | 7      |            |            |         |
| `commands/list/all.feature`        | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/list/sketches.feature`   | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/list/interfaces.feature` | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/list/mates.feature`      | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/list/parts.feature`      | 23     | 0      | 0         | N/A      | 0      |            |            |         |
| `commands/list/assemblies.feature` | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/render.feature`          | 0      | 0      | 0         | N/A      | 72     |            |            |         |
| `commands/inspect.feature`         | 0      | 0      | 0         | N/A      | 304    |            |            |         |
| `commands/status.feature`          | 22     | 0      | 6         | N/A      | 7      |            |            |         |
| `commands/test.feature`            | 0      | 0      | 0         | N/A      | 7      |            |            |         |
| `commands/ai/regenerate.feature`   | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/supply/find.feature`     | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/supply/caps.feature`     | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/supply/quote.feature`    | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| `commands/supply/order.feature`    | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |

## Roadmap

- [ ] Write help to STDERR
  - [ ] https://github.com/ewels/rich-click/pull/217
- [ ] Add `--help` scenario to all commands.
- [ ] Make `version` work without `--format level`
  - [ ] Use `pc_logger`
- [ ] Run `partcad list all` as `partcad list`
