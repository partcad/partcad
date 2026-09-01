## The examples this IDE carries

| | What it shows |
| --- | --- |
| **A part in CadQuery** | A cube and a cylinder as CadQuery scripts, and the same cube declared again at other dimensions -- `enrich` and `alias`, which is how a package reuses a shape without copying it |
| **A part in build123d** | The smallest package there is: one script, one entry under `parts:` |
| **A part in OpenSCAD** | A `.scad` file used as it is, and a parameterized module PartCAD instantiates with arguments from `partcad.yaml` |
| **An assembly** | Parts placed relative to each other in an `.assy` file, taken from *other* packages -- which is what a package manager for CAD is for |

They are the examples this project publishes, unchanged. The one you pick is
copied into `~/.partcad/projects/start`, next to your own package, with whatever
packages it uses beside it -- an assembly brings the packages its parts come
from. A copy you have already edited is left alone.

Everything in them is yours to change: they are files in your home directory,
not something inside the application.

### Documentation

* [Tutorial](https://partcad.readthedocs.io/en/latest/tutorial.html)
* [Assemblies](https://partcad.readthedocs.io/en/latest/assy.html)
* [Configuration reference](https://partcad.readthedocs.io/en/latest/configuration.html)
* [All the examples, on GitHub](https://github.com/partcad/partcad/tree/main/examples)
