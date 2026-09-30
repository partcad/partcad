## The command line

```shell
pc list parts      # what is in this package
pc render          # draw it
pc export -t step  # hand it to another tool
pc healthcheck     # what PartCAD needs on this machine, and what is missing
```

The IDE ships `pc` and points the PartCAD extension at it, so the terminal in
this window has it on the PATH already -- no `pip install`, no virtual
environment, no Python at all.

`pc --help` lists the commands. They are the same ones the extension runs for
you, and both talk to the same PartCAD service.

### Documentation

* [CLI command reference](https://partcad.readthedocs.io/en/latest/cli.html)
* [Installing PartCAD elsewhere](https://partcad.readthedocs.io/en/latest/installation.html)
* [When something does not work](https://partcad.readthedocs.io/en/latest/troubleshooting.html)
