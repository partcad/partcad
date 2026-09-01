## Rendering

```shell
pc render          # every projection and document the package declares
pc export -t stl   # the 3D file another tool wants
```

`pc render` draws the package: SVG and PNG projections, a PDF or an HTML
document, a DXF for a laser cutter, and the `README.md` an assembly's
instruction book goes into. What each object renders to is declared in
`partcad.yaml`, so everyone who has the package gets the same files.

`pc export` is the other direction -- STEP, STL, 3MF, OBJ, glTF, IGES -- and
the Explorer's context menu has the same formats under "Export".

The "Render" entry in the Run and Debug view runs `pc render` in this
workspace. `pc init` put it there when it created the package.

### Documentation

* [`pc render`, `pc export` and their options](https://partcad.readthedocs.io/en/latest/cli.html)
* [What a package declares to render](https://partcad.readthedocs.io/en/latest/configuration.html)
* [Tutorial: export the part](https://partcad.readthedocs.io/en/latest/tutorial.html)
