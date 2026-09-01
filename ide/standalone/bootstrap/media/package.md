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

The editor asks whether you trust the authors of a folder before it runs
anything from it. This one it made for you, so the answer is yes -- and
PartCAD stays quiet until you give it.

Nothing here is special to the IDE. Copy the folder somewhere else, put it in
git, or make another one with `pc init` -- it is a package either way.
