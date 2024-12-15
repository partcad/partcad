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
    init                Create a new PartCAD package in the current directory
    info                Show detailed information about a part, assembly, or scene
    install             Download and set up all imported packages
    update              Refresh all imported packages
    list                List imported packages
    list-all            List available parts, assemblies and scenes
    list-sketches       List available sketches
    list-interfaces     List available interfaces
    list-mates          List available mating interfaces
    list-parts          List available parts
    list-assemblies     List available assemblies
    render              Generate a rendered view of parts, assemblies, or scenes in the package
    inspect             View a part, assembly, or scene visually
    status              Show the current state of PartCAD's internal data
    test                Generate a rendered view of parts, assemblies, or scenes in the package
    ai                  Execute AI-related commands
    supply              Manage supplier-related tasks

options:
  -h, --help            show this help message and exit
  -v                    Increase verbosity level
  -q                    Decrease verbosity level
  --no-ansi             Produce plain text logs without colors or animations
  -p CONFIG_PATH        Specify the package path (YAML file or directory with 'partcad.yaml')

took 2s
```

## New command line interface

```text
⬢ [Docker] ❯ partcad --help

 Usage: partcad [OPTIONS] COMMAND [ARGS]...


 ██████╗  █████╗ ██████╗ ████████╗ ██████╗ █████╗ ██████╗
 ██╔══██╗██╔══██╗██╔══██╗╚══██╔══╝██╔════╝██╔══██╗██╔══██╗
 ██████╔╝███████║██████╔╝   ██║   ██║     ███████║██║  ██║
 ██╔═══╝ ██╔══██║██╔══██╗   ██║   ██║     ██╔══██║██║  ██║
 ██║     ██║  ██║██║  ██║   ██║   ╚██████╗██║  ██║██████╔╝
 ╚═╝     ╚═╝  ╚═╝╚═╝  ╚═╝   ╚═╝    ╚═════╝╚═╝  ╚═╝╚═════╝

╭─ Options ────────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│            -v                     Increase verbosity level                                                    │
│            -q                     Decrease verbosity level                                                    │
│ --no-ansi                         Produce plain text logs without colors or animations                             │
│            -p  PATH               Specify the package path (YAML file or directory with 'partcad.yaml')                      │
│ --format       [time|path|level]  Set the log prefix format                                                                  │
│ --help                            Show this message and exit.                                                        │
╰──────────────────────────────────────────────────────────────────────────────────────────────────────────────────────╯
╭─ Commands ───────────────────────────────────────────────────────────────────────────────────────────────────────────╮
│ add                               Add a package, part, or assembly                                          │
│ info                              Show detailed information about a part, assembly, or scene                                    │
│ init                              Create a new PartCAD package in the current directory                                 │
│ inspect                           View a part, assembly, or scene visually                                                │
│ install                           Download and set up all imported packages                                         │
│ list                              List components                                                                    │
│ render                            Generate a rendered view of parts, assemblies, or scenes in the package            │
│ status                            Show the current state of PartCAD's internal data                                 │
│ supply                            Manage supplier-related tasks                                                          │
│ test                              Generate a rendered view of parts, assemblies, or scenes in the package            │
│ update                            Refresh all imported packages                                                       │
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

| `features/partcad-cli/commands/...` | Passed | Failed | Undefined | Coverage | `@wip` | `@success` | `@failure` | `@help` |
| ----------------------------------- | ------ | ------ | --------- | -------- | ------ | ---------- | ---------- | ------- |
| ✔ `../pc.feature`                   | 57     | 0      | 0         | N/A      | 19     |            |            |         |
| ✔ `version.feature`                 | 8      | 0      | 0         | N/A      | 0      |            |            |         |
| ✔ `add/package.feature`             | 19     | 0      | 0         | N/A      | 0      |            |            |         |
| ✔ `add/part.feature`                | 12     | 0      | 0         | N/A      | 185    |            |            |         |
| 🚧 `add/assembly.feature`           | 0      | 0      | 0         | N/A      | 30     |            |            |         |
| ✔ `init.feature`                    | 22     | 0      | 0         | N/A      | 20     |            |            |         |
| ✔ `info.feature`                    | 0      | 0      | 0         | N/A      | 30     |            |            |         |
| ✔ `install.feature`                 | 7      | 0      | 0         | N/A      | 25     |            |            |         |
| ✔ `update.feature`                  | 9      | 0      | 0         | N/A      | 0      |            |            |         |
| ✔ `list/packages.feature`           | 15     | 0      | 4         | N/A      | 7      |            |            |         |
| 🚧 `list/all.feature`               | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ✔ `list/sketches.feature`           | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ✔ `list/interfaces.feature`         | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| 🚧 `list/mates.feature`             | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ✔ `list/parts.feature`              | 23     | 0      | 0         | N/A      | 0      |            |            |         |
| ✔ `list/assemblies.feature`         | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ✔ `render.feature`                  | 0      | 0      | 0         | N/A      | 72     |            |            |         |
| 🚧 `inspect.feature`                | 0      | 0      | 0         | N/A      | 304    |            |            |         |
| ✔ `status.feature`                  | 15     | 0      | 0         | N/A      | 20     |            |            |         |
| 🚧 `test.feature`                   | 0      | 0      | 0         | N/A      | 7      |            |            |         |
| ❌ `ai/regenerate.feature`          | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ❌ `supply/find.feature`            | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ❌ `supply/caps.feature`            | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ❌ `supply/quote.feature`           | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |
| ❌ `supply/order.feature`           | N/A    | N/A    | N/A       | N/A      | N/A    |            |            |         |

## Roadmap

- [ ] Write help to STDERR
  - [ ] Add stream configuration options in [rich-click PR #217](https://github.com/ewels/rich-click/pull/217)
- [ ] Add `--help` scenario to all commands.
  - [ ] Each `$command.feature` should have a `--help` scenario
- [ ] Run `partcad list all` as `partcad list`
- [x] Make `version` work without `--format level`
  - [x] Use `pc_logger`

## Closure

- [ ] Install new CLI as `pc`.
  - [ ] Update command name in `*.feature`.
- [ ] Cleanup `*.feature` tests.
  - [ ] Fix tests where possible.
    - [x] `features/partcad-cli/pc.feature:9`: Show CLI help
    - [x] `features/partcad-cli/pc.feature:35`: Do not show INFO messages with decreased verbosity
    - [x] `features/partcad-cli/pc.feature:47`: Do not show ANSI codes
    - [x] `features/partcad-cli/commands/add/assembly.feature:8`: Add assembly from `logo.assy` file
      - [ ] `PC-162`
    - [x] `features/partcad-cli/commands/list/parts.feature:41`: List parts with invalid configuration
      - [ ] https://partcad.atlassian.net/browse/PC-163
      - [ ] https://github.com/ewels/rich-click/pull/217
    - [x] `features/partcad-cli/commands/supply/quote.feature:6`: Generate quote for available parts
      - [ ] https://partcad.atlassian.net/browse/PC-164
    - [x] `features/partcad-cli/commands/supply/quote.feature:13`: Handle quote for unavailable parts
      - [ ] https://partcad.atlassian.net/browse/PC-164
  - [x] Add `@wip` to tests that are not yet finished.
- [ ] Update `./docs`
- [ ] Run `behave` in CI.
