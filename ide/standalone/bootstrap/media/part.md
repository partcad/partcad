## Parts

A part is one shape, produced by one script:

```python
# a CadQuery part
import cadquery as cq

result = cq.Workplane("XY").box(10, 10, 10)
```

...and one entry in `partcad.yaml`:

```yaml
parts:
  box:
    type: cadquery
```

"Add a part" writes both. It asks for a name and a type -- CadQuery, build123d
and OpenSCAD are scripts; STEP, STL, 3MF and DXF are files PartCAD imports as
they are.

Parts take parameters, so one script can be a family of parts. Assemblies put
parts together, and are added the same way.

### Documentation

* [Parts, and every type of them](https://partcad.readthedocs.io/en/latest/configuration.html)
* [Tutorial: add a part](https://partcad.readthedocs.io/en/latest/tutorial.html)
* [Parameters and interfaces](https://partcad.readthedocs.io/en/latest/configuration.html)
