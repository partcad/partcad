# partcad-cli

A compatibility shim. The PartCAD command line interface ships inside the
[`partcad`](https://pypi.org/project/partcad/) package, which is what this
depends on and what you should install:

```shell
pip install partcad
```

Installing `partcad-cli` still works and still gives you `pc` and `partcad` —
it just gets them from `partcad`, which it pulls in. This package contains no
code of its own.
