# PartCAD <!-- omit in toc -->

[![License](https://github.com/openvmp/partcad/blob/main/apache20.svg?raw=true)](./LICENSE.txt)

[![CI on Linux, MacOS and Windows](https://github.com/openvmp/partcad/actions/workflows/python-test.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-test.yml)
[![CD on Linux, MacOS and Windows](https://github.com/openvmp/partcad/actions/workflows/python-build.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-build.yml)
[![Deployment to PyPI](https://github.com/openvmp/partcad/actions/workflows/python-deploy.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-deploy.yml)
[![Documentation Status](https://readthedocs.org/projects/partcad/badge/?version=latest)](https://partcad.readthedocs.io/en/latest/?badge=latest)
<a href="https://discord.gg/AXbP47zYw5"><img alt="Discord" src="https://img.shields.io/discord/1091497262733074534?logo=discord&logoColor=white&label=Discord&labelColor=353c43&color=31c151"></a>

PartCAD is the first package manager for CAD models
and a framework for managing assemblies.
It aims to complement Git with everything necessary to substitute
commercial Product Lifecycle Management (PLM) tools.

PartCAD maintains information about mechanical parts and
how they come together to form larger assemblies.
The same parts can be reused in multiple assemblies and multiple projects.
And all of that is supercharged by the ultimate versioning and collaboration features of Git.

PartCAD features include:

- 3D part models using [CadQuery](https://cadquery.readthedocs.io/), [build123d](https://build123d.readthedocs.io/) and [OpenSCAD](https://openscad.org/) scripting languages
- 3D part models using legacy STEP, STL and 3MF files
- Generate 3D models using LLM/GenAI: Google AI (Gemini), OpenAI (ChatGPT) or any model published to [Ollama](https://ollama.com/) (Llama 3.1, DeepSeek-Coder-V2, CodeGemma, Code Llama etc)
- 2D blueprints using [build123d](https://build123d.readthedocs.io/), or legacy DXF and SVG files
- Fully featured object-oriented approach to maintaining part interfaces and mating information (with multiple class inheritance etc)
- Live preview of 3D models while coding in VS Code
- Render models to SVG, PNG and export to STEP, STL, 3MF, ThreeJS and OBJ
- Render Markdown documentation files

Find [more documentation here](https://partcad.readthedocs.io/en/latest/?badge=latest) and visit [our website](https://partcad.org/).

## Installation

### Extension for Visual Studio Code

This extension can be installed by searching for `PartCAD` in VS Code extension search form, or by browsing [its VS Code marketplace page](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad).

[![PartCAD Visual Studio Code extension](./docs/source/images/vscode1.png)](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad)

### Command-Line Interface

The recommended method to install PartCAD CLI tools for most users is:

```shell
pip install -U partcad-cli
```

For contributors:

```shell
git clone https://github.com/openvmp/partcad.git
cd partcad
python3 -m pip install -U -e ./partcad
python3 -m pip install -U -e ./partcad-cli
```

PartCAD works best when [conda](https://docs.conda.io/) is installed.
If that doesn't help (e.g. MacOS+arm64) then try ``mamba``.
On Windows, PartCAD requires at least a `conda` environment.
On Ubuntu, try `apt install libcairo2-dev` if `pip install` fails to install `cairo`.

## Architecture

![Architecture](https://github.com/openvmp/partcad/blob/main/docs/source/images/architecture.png?raw=true)

## Tools for Mechanical Engineering

Here is an overview of open source tools to maintain
mechanical projects. It demonstrates where PartCAD fits
in the modern mechanical development workflows.

```mermaid
flowchart TB

subgraph repo["Your project's GIT repository"]
  subgraph custom_repo["Custom parts"]
    direction TB
    custom_part_internet["A STEP file\ndownloaded from Internet\nor the vendor site"]
    custom_part_cad["A part exported as a solid\nfrom a CAD tool not\nsuitable for collaboration"]
    custom_part_cq["An individual reusable part\nmaintained as a script\nunder a version control system"]
    custom_part_os["Another reusable part\nmaintained as a script\nunder a version control system"]
  end

  model["Your project's model defined\nas ASSY or Python code\nfor version control\nand collaboration"]

  subgraph scenes["Scenes"]
    test1["Capability 1\ntest scene"]
    test2["Capability 2\ntest scene"]
  end
end

subgraph external_repos["Third-party GIT repositories,\nCDN-hosted files or OCCI servers"]
  subgraph external_repo["Repository of standard\nor popular parts"]
  end
end

subgraph external_tools["External tools"]
  freecad["FreeCAD"]
  cadquery["CadQuery / build123d"]
  openscad["OpenSCAD"]
  gazebo["Gazebo"]

  partcad["PartCAD library"]
  style partcad fill:#c00
end

custom_part_cad <--- |Individual\ncontributor|freecad
custom_part_cq <--- |Part design\nworkflow| cadquery
custom_part_os <--- |Part design\nworkflow| openscad

external_repo ---> |Import| model
custom_repo ---> |Import| model
model -.-> |Import| test1
model -.-> |Import| test2

custom_repo <-. Maintained\nusing\nPartCAD\nconvention .- partcad
external_repo <-. Maintained\nusing\nPartCAD\nconvention .- partcad
model <--- partcad
test1 <--- partcad
test2 <--- partcad

test1 -.-> |Export| gazebo
test2 -.-> |Export| gazebo
```

## Development

```bash
poetry completions bash >> ~/.bash_completion
```

```bash
cd partcad-cli
poetry install
```

## Roadmap

- [ ] Move poetry completions to the dotfiles repo.
- [ ] Move from Python 3.10 to 3.12.
- [ ] Configure dev dependencies for `partcad-cli`.
- [ ] Add JSON Schema for `partcad.yaml`.

[CadQuery]: https://github.com/CadQuery/cadquery
[build123d]: https://github.com/gumyr/build123d
[STEP]: https://en.wikipedia.org/wiki/ISO_10303
[OpenCASCADE]: https://www.opencascade.com/
