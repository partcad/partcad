# PartCAD <!-- omit in toc -->

[![License](https://github.com/openvmp/partcad/blob/main/apache20.svg?raw=true)](./LICENSE.txt)

[![CI on MacOS and Windows](https://github.com/openvmp/partcad/actions/workflows/python-test.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-test.yml)
[![CI on Linux](https://github.com/partcad/partcad/actions/workflows/dev-container.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/dev-container.yml)
[![CD on Linux, MacOS and Windows](https://github.com/openvmp/partcad/actions/workflows/python-build.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-build.yml)
[![Deployment to PyPI](https://github.com/openvmp/partcad/actions/workflows/python-deploy.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-deploy.yml)
[![Documentation Status](https://readthedocs.org/projects/partcad/badge/?version=latest)](https://partcad.readthedocs.io/en/latest/?badge=latest)
<a href="https://discord.gg/9AEu3vF7rv"><img alt="Discord" src="https://img.shields.io/discord/1091497262733074534?logo=discord&logoColor=white&label=Discord&labelColor=353c43&color=31c151"></a>
[![Nox](https://img.shields.io/badge/%F0%9F%A6%8A-Nox-D85E00.svg)](https://github.com/wntrblm/nox)

[PartCAD] is **the first package manager for CAD models** and a framework for managing assemblies.

It aims to complement Git with everything necessary for hardware development to substitute commercial Product Lifecycle
Management (PLM) tools. It's a free versioning and change management solution for all your CAD needs, built around your
CAD artifacts instead of being built into your CAD tool.

Browse [our documentation] and visit [our website]. Watch our 💥💥[demos](https://youtube.com/@PartCAD)💥💥.

## Join us!

Stay informed and share feedback by joining [our Discord server](https://discord.gg/9AEu3vF7rv). <br/>

Subscribe on [LinkedIn], [YouTube], [TikTok], [Facebook], [Instagram], [Threads] and [Twitter/X].

[![PartCAD Visual Studio Code extension](../docs/source/images/vscode1.png)](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad)

## Features

- Multiple OSes supported
  - [x] Windows
  - [x] Linux
  - [x] macOS
- Collaboration on designs
  - [x] Versioning of CAD designs using `Git` _(like it's 2024 for real)_
    - [x] Mechanics
    - [ ] Electronics _(in progress)_
    - [ ] Software _(in progress)_
  - [x] Automated generation of `Markdown` documentation
  - [x] Parametric (hardware and software) bill of materials
  - [x] Publish models online on PartCAD.org
  - [ ] Publish models online on your website _(in progress)_
  - [ ] Publish configurable parts and assemblies online _(in progress)_
  - [ ] Purchase of assemblies and parts online, both marketplace and SaaS _(in progress)_
  - [x] Automated purchase of parts via CLI
- Assembly models (3D)
  - [x] Using specialized `Assembly YAML` format
    - [x] Automatically maintaining the bill of materials
    - [ ] Generating user-friendly visual assembly instructions _(in progress)_
  - [ ] Generating with LLM/GenAI _(in progress)_
- Part models (3D)
  - Using scripting languages
    - [x] [CadQuery]
    - [x] [build123d]
    - [x] [OpenSCAD]
  - Using legacy CAD files
    - [x] `STEP`
    - [x] `STL`
    - [x] `3MF`
  - Generating with LLM/GenAI
    - [x] Google AI (`Gemini`)
    - [x] OpenAI (`ChatGPT`)
    - [x] Any model in [Ollama](https://ollama.com/) (`Llama 3.1`, `DeepSeek-Coder-V2`, `CodeGemma`, `Code Llama` etc.)
- Part and interface blueprints (2D)
  - Using scripting languages
    - [x] [CadQuery]
    - [x] [build123d]
  - Using legacy file formats:
    - [x] `DXF`
    - [x] `SVG`
- Other features
  - Object-Oriented Programming approach to maintaining part interfaces and mating information
  - Live preview of 3D models while working in Visual Studio Code
  - Render 2D and 3D to images
    - [x] `SVG`
    - [x] `PNG`
  - Export 3D models to CAD files
    - [x] `STEP`
    - [x] `STL`
    - [x] `3MF`
    - [x] `ThreeJS`
    - [x] `OBJ`

## Installation

Note, it's not required but highly recommended that you have [conda] installed. If you experience any difficulty
installing or using any PartCAD tool, then make sure to install [conda].

### Extension for Visual Studio Code

This extension can be installed by searching for `PartCAD` in the VS Code extension search form, or by browsing
[its VS Code marketplace page](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad).

Make sure to have Python configured and a [conda] environment set up in VS Code before using PartCAD.

### Command-Line Interface

The recommended method to install PartCAD CLI tools for most users is:

```shell
pip install -U partcad-cli
```

- On **Windows**, install `Miniforge3` using `Register Miniforge3 as my default Python X.XX` and use this Python
  environment for PartCAD. Also set `LongPathsEnabled` to 1 at
  `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem` using `Registry Editor`.
- On **Ubuntu**, try `apt install libcairo2-dev python3-dev` if `pip install` fails to install `cairo`.
- On **macOS**, make sure XCode and command lines tools are installed. Also, use `mamba` should you experience
  difficulties on macOS with the ARM architecture.

### PartCAD development

Refer to the [Quick Start] guide for step-by-step instructions on setting up your development environment, adding
features, and running tests.

## Getting Started

See the tutorials for [PartCAD command line tools](https://partcad.readthedocs.io/en/latest/tutorial.html#command-line)
or [PartCAD Visual Studio Code extension](https://partcad.readthedocs.io/en/latest/tutorial.html#vs-code-extension).

## Have you read this page this far?

Give us a star for our hard work!

[PartCAD]: https://partcad.org/
[our website]: https://partcad.org/
[our documentation]: https://partcad.readthedocs.io/en/latest/?badge=latest
[LinkedIn]: https://linkedin.com/company/partcad
[YouTube]: https://youtube.com/@PartCAD
[TikTok]: https://tiktok.com/@partcad
[Facebook]: https://www.facebook.com/profile.php?id=61568171037701
[Instagram]: https://instagram.com/partcadofficial
[Twitter/X]: https://x.com/PartCAD
[Threads]: https://threads.net/@partcadofficial
[conda]: https://docs.conda.io/
[CadQuery]: https://github.com/CadQuery/cadquery
[build123d]: https://github.com/gumyr/build123d
[OpenSCAD]: https://openscad.org/
[STEP]: https://en.wikipedia.org/wiki/ISO_10303
[OpenCASCADE]: https://www.opencascade.com/
[Quick Start]: https://partcad.github.io/partcad/development/quick-start/
