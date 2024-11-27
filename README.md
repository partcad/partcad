# PartCAD <!-- omit in toc -->

[![License](https://github.com/openvmp/partcad/blob/main/apache20.svg?raw=true)](./LICENSE.txt)

[![CI on Linux, MacOS and Windows](https://github.com/openvmp/partcad/actions/workflows/python-test.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-test.yml)
[![CD on Linux, MacOS and Windows](https://github.com/openvmp/partcad/actions/workflows/python-build.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-build.yml)
[![Deployment to PyPI](https://github.com/openvmp/partcad/actions/workflows/python-deploy.yml/badge.svg)](https://github.com/openvmp/partcad/actions/workflows/python-deploy.yml)
[![Documentation Status](https://readthedocs.org/projects/partcad/badge/?version=latest)](https://partcad.readthedocs.io/en/latest/?badge=latest)
<a href="https://discord.gg/zdwyxkGM"><img alt="Discord" src="https://img.shields.io/discord/1091497262733074534?logo=discord&logoColor=white&label=Discord&labelColor=353c43&color=31c151"></a>

[PartCAD] is the first package manager for CAD models
and a framework for managing assemblies.
It aims to complement Git with everything necessary for hardware development
to substitute commercial Product Lifecycle Management (PLM) tools.
It is a free versioning and change management system for your CAD,
but built around your CAD artifacts instead of being built in into your CAD tool.

[PartCAD] maintains information about mechanical parts and
how they come together to form larger assemblies.
The same parts can be reused in multiple assemblies and multiple projects.
And all of that is supercharged by the ultimate versioning and collaboration features of Git.

## Join PartCAD

Participate in defining the roadmap on [our Patreon page](https://patreon.com/PartCAD).
<br/>
Stay informed by joining [our Discord server](https://discord.gg/zdwyxkGM).
<br/>
Subscribe on [LinkedIn], [YouTube], [TikTok], [Facebook], [Instagram], [X] and [Threads].

## Features

Here is a brief description of PartCAD features:

- 3D part models using [CadQuery], [build123d] and [OpenSCAD] scripting languages
- 3D part models using legacy `STEP`, `STL` and `3MF` files
- Generate 3D models using LLM/GenAI: Google AI (`Gemini`), OpenAI (`ChatGPT`) or any model published to [Ollama](https://ollama.com/) (`Llama 3.1`, `DeepSeek-Coder-V2`, `CodeGemma`, `Code Llama` etc)
- 2D blueprints using [build123d], or legacy `DXF` and `SVG` files
- Object-Oriented Programming approach to maintaining part interfaces and mating information
- Live preview of 3D models while coding in VS Code
- Render models to `SVG`, `PNG` and export to `STEP`, `STL`, `3MF`, `ThreeJS` and `OBJ`
- Render `Markdown` documentation files

## Documentation

Browse [our documentation] and visit [our website].

## Installation

Note: It's not required but highly recommended to have [conda] installed.
If you experience any difficulty installing or using any PartCAD tool then make sure to install [conda].

### Extension for Visual Studio Code

This extension can be installed by searching for `PartCAD` in the VS Code extension search form, or by browsing [its VS Code marketplace page](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad).

Make sure to have Python configured and a [conda] environment set up in VS Code before using PartCAD.

[![PartCAD Visual Studio Code extension](./docs/source/images/vscode1.png)](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad)

### Command-Line Interface

The recommended method to install PartCAD CLI tools for most users is:

```shell
pip install -U partcad-cli
```

- On **Windows**, PartCAD must be executed inside a [conda] environment. Also set `LongPathsEnabled` to 1 at `HKEY_LOCAL_MACHINE\SYSTEM\CurrentControlSet\Control\FileSystem` using `Registry Editor`.
- On **Ubuntu**, try `apt install libcairo2-dev python3-dev` if `pip install` fails to install `cairo`.
- On **MacOS**, make sure XCode and command lines tools are installed. Also, use ``mamba`` should you experience difficulties on MacOS with the arm64 architecture.

### PartCAD development

The recommended first steps for PartCAD developers are:

```shell
git clone https://github.com/openvmp/partcad.git
cd partcad
python3 -m pip install -U -e ./partcad
python3 -m pip install -U -e ./partcad-cli
```

[PartCAD]: https://partcad.org/
[our website]: https://partcad.org/
[our documentation]: https://partcad.readthedocs.io/en/latest/?badge=latest
[LinkedIn]: https://linkedin.com/company/partcad
[YouTube]: https://youtube.com/@PartCAD
[TikTok]: https://tiktok.com/@partcad
[Facebook]: https://www.facebook.com/profile.php?id=61568171037701
[Instagram]: https://instagram.com/partcadofficial
[X]: https://x.com/PartCAD
[Threads]: https://threads.net/@partcadofficial
[conda]: https://docs.conda.io/
[CadQuery]: https://github.com/CadQuery/cadquery
[build123d]: https://github.com/gumyr/build123d
[OpenSCAD]: https://openscad.org/
[STEP]: https://en.wikipedia.org/wiki/ISO_10303
[OpenCASCADE]: https://www.opencascade.com/
