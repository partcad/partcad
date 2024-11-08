# partcad

PartCAD is the first package manager for CAD models
and a framework for managing assemblies.
It aims to complement Git with everything necessary to substitute
commercial Product Lifecycle Management (PLM) tools.

PartCAD maintains information about mechanical parts and
how they come together to form larger assemblies.
The same parts are reused in multiple assemblies and multiple projects.
And all of that is supercharged by the ultimate versioning and collaboration features of Git.

This Python module is the core part of PartCAD.
It can be used in Python scripts to instantiate parts,
assemblies and scenes implemented as PartCAD packages.
Such instances can be used in [CadQuery] and [build123d] scripts.
They can also be used in custom web, mobile and desktop applications
that render CAD models.
This module can also be used to generate BoMs (bills of materials) and assembly
instructions.

For PartCAD command line tools, see the Python module `partcad-cli` instead.

See [the main PartCAD repo](https://github.com/openvmp/partcad/) for more information.

[CadQuery]: https://github.com/CadQuery/cadquery
[build123d]: https://github.com/gumyr/build123d
