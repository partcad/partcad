# CLI

## Roadmap

- [ ] Write help to STDERR
  - [ ] Add stream configuration options in [rich-click PR #217](https://github.com/ewels/rich-click/pull/217)
- [ ] Add `--help` scenario to all commands.
  - [ ] Each `$command.feature` should have a `--help` scenario
- [ ] Run `partcad list all` as `partcad list`
- [x] Make `version` work without `--format level`
  - [x] Use `pc_logger`
- [ ] Configure 1Password CLI completions
  - [ ] `op completion ...`
- [ ] Create Dev Container Feature to install 1Password CLI
  - [ ] https://developer.1password.com/docs/cli/get-started/#step-1-install-1password-cli
- [ ] Convert all TODOs to issues
- [ ] Update https://partcad.readthedocs.io

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
- "Critical Path?" from some book.
  - Closure: fix value, merge PR & etc.
  - Short term aka immediate Goals
- Get rid of `partcad-cli` and `commands`
- [ ] TODO: Fix `behave`
