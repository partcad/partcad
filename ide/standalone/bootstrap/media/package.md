## The starter package

```
~/.partcad/projects/start
├── partcad.yaml      the package: what is in it, and what it depends on
└── .vscode
    └── launch.json   the "Render" command, in the Run and Debug view
```

`partcad.yaml` is the whole package. Parts, assemblies and sketches are listed
in it, and so are the packages this one depends on -- including `pub`, the
public PartCAD index, which every new package starts with.

The PartCAD Explorer, on the left, shows the same file as a tree: the packages
it can reach, and the objects in them.

PartCAD runs the code in the packages you open -- that is what building a
part from a script means. The PartCAD IDE exists for that, so it does not ask
whether you trust a folder before PartCAD opens it: open only packages you
would run. (In Visual Studio Code, which asks, PartCAD waits for the answer.)

Nothing here is special to the IDE. Copy the folder somewhere else, put it in
git, or make another one with `pc init` -- it is a package either way.

### Documentation

* [Packages and dependencies](https://partcad.readthedocs.io/en/latest/configuration.html)
* [Tutorial: create a package](https://partcad.readthedocs.io/en/latest/tutorial.html)
* [What `pc init` writes](https://partcad.readthedocs.io/en/latest/cli.html)
