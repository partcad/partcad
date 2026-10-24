# PartCAD <!-- omit in toc -->

[![CI on Linux, macOS and Windows](https://github.com/partcad/partcad/actions/workflows/test.yml/badge.svg?event=schedule)](https://github.com/partcad/partcad/actions/workflows/test.yml?query=event%3Aschedule)
[![PyPI](https://img.shields.io/pypi/v/partcad)](https://pypi.org/project/partcad/)
[![Documentation Status](https://readthedocs.org/projects/partcad/badge/?version=latest)](https://partcad.readthedocs.io/en/latest/?badge=latest)
[![Discord](https://img.shields.io/discord/1308854595987968051?logo=discord&logoColor=white&label=Discord&labelColor=353c43&color=31c151)](https://discord.gg/h5qhbHtygj)
[![License](https://img.shields.io/badge/license-Apache%202.0-blue.svg)](https://github.com/partcad/partcad/blob/main/LICENSE.txt)

**[PartCAD] is the programming language for manufacturable things.**

A package is a Git repository with a `partcad.yaml` that declares parts (CAD scripts or files), assemblies,
materials and requirements. PartCAD renders, tests, simulates, analyses and documents them, and produces the
bill of materials, the sourcing and the assembly instructions from that same source. Everything is text, so it
is versioned, reviewed and generated like software, by people and by AI agents.

[Documentation](https://partcad.readthedocs.io/) · [Website](https://partcad.org/) ·
[Demos](https://youtube.com/@PartCAD) · [Discord](https://discord.gg/h5qhbHtygj)

[![PartCAD in Visual Studio Code](https://github.com/partcad/partcad/blob/main/docs/source/images/vscode1.png?raw=true)](https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad-official)

## Install

Pick one. Every option ends up with the same `pc` command line tool and the same packages.

| You have           | Install                                                                                                                                                                                                                              |
| ------------------ | ------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| Nothing yet        | The **PartCAD IDE**: `curl -fsSL https://raw.githubusercontent.com/partcad/partcad/main/install.sh \| sh -s -- --ide`, or the Windows and macOS installers on the [releases page](https://github.com/partcad/partcad/releases) |
| Python             | `pip install -U partcad`                                                                                                                                                                                                             |
| Visual Studio Code | `code --install-extension PartCAD.partcad-official` ([marketplace](https://marketplace.visualstudio.com/items?itemName=PartCAD.partcad-official))                                                                                     |
| Claude Code        | `/plugin marketplace add partcad/partcad@plugin-dist`, then `/plugin install pc@partcad`, then `/pc:setup`                                                                                                                            |

The standalone command line tools without Python, the snap, the FreeCAD add-on, the MCP server for other AI
agents, and the per-OS notes are all in
[Installation](https://partcad.readthedocs.io/en/latest/installation.html).

## Try it

```shell
pc init                      # a package in the current directory, with agent skills for Claude Code and Cursor
pc ide view my_part          # show it in the Digital Thread of the IDE or the extension
pc render my_part            # SVG, PNG, DXF... from any angle
pc test                      # the ports, interfaces, physics and simulations the objects declare
pc instructions my_assembly  # the assembly instruction book, PDF or HTML, with the bill of materials
```

Or, in Claude Code, `/pc:gen a mounting bracket with four M4 holes`: the agent writes the CAD script, renders
it and checks the result against what was asked.

The [tutorial](https://partcad.readthedocs.io/en/latest/tutorial.html) walks through a first package, and
[`examples/`](https://github.com/partcad/partcad/tree/main/examples) has one directory per feature.

## What it does

- **Parts** from [CadQuery], [build123d], [OpenSCAD], [Chili3D], [SDF], STEP, BREP, STL, 3MF, OBJ, glTF,
  [KiCad EDA] PCBs, FreeCAD documents, and any format a plugin package adds ([SolidCraft], Rhino, IGES).
- **Assemblies and scenes** in Assembly YAML, URDF or a STEP file, with interfaces and mating as objects.
- **Outputs**: STEP, BREP, STL, 3MF, OBJ, IGES, glTF, URDF, Gazebo and MuJoCo worlds, 2D projections,
  dimensioned drawings, Markdown documentation and PDF or HTML instruction books.
- **Engineering**: FEA, modal, thermal and CFD analysis (`pc cae`), simulation in MuJoCo or Gazebo
  (`pc sim`), 2.5D toolpaths (`pc cam`), and materials and manufacturing methods carried into the bill of
  materials.
- **Supply chain**: a Build vs Buy decision per line item, stock-based procurement for made parts, and
  automated purchasing from the command line.
- **AI agents**: Agent Skills for Claude Code and Cursor, an MCP server (`pc mcp`), and plain-text
  `--no-ansi` output on every command.
- **Caching** in memory, on disk, in memcached and in S3, so a team or a CI fleet renders each model once.

The full list of what is supported, and what is still in progress, is in
[Supported formats and features](https://partcad.readthedocs.io/en/latest/supported.html).

## Why

PartCAD is not a drawing tool. It is the layer under the drawing tools: the specification of a manufacturable
product, kept in a form that a human, a CI job and an AI model can all read, change and verify. Keeping that
specification on-prem, in Git, and portable between CAD tools and manufacturers is the point. See
[Introduction](https://partcad.readthedocs.io/en/latest/intro.html) and
[Use cases](https://partcad.readthedocs.io/en/latest/use_cases.html).

## Community

Questions and feedback go to [Discord](https://discord.gg/h5qhbHtygj); bugs and ideas to
[GitHub issues](https://github.com/partcad/partcad/issues). Follow [LinkedIn], [YouTube] and [Twitter/X] for
releases. To contribute, start with
[Contributing](https://partcad.readthedocs.io/en/latest/contributing.html).

Licensed under [Apache 2.0](https://github.com/partcad/partcad/blob/main/LICENSE.txt).

<!-- mcp-name: io.github.partcad/partcad -->

[PartCAD]: https://partcad.org/
[LinkedIn]: https://linkedin.com/company/partcad
[YouTube]: https://youtube.com/@PartCAD
[Twitter/X]: https://x.com/PartCAD
[CadQuery]: https://github.com/CadQuery/cadquery
[build123d]: https://github.com/gumyr/build123d
[Chili3D]: https://github.com/xiangechen/chili3d
[OpenSCAD]: https://openscad.org/
[SDF]: https://github.com/fogleman/sdf
[KiCad EDA]: https://www.kicad.org/
[SolidCraft]: https://github.com/bherbruck/solidcraft
