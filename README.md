# PartCAD <!-- omit in toc -->

[![License](https://github.com/partcad/partcad/blob/main/apache20.svg?raw=true)](./LICENSE.txt)

[![CI on Linux, macOS and Windows](https://github.com/partcad/partcad/actions/workflows/test.yml/badge.svg?event=schedule)](https://github.com/partcad/partcad/actions/workflows/test.yml?query=event%3Aschedule)
[![CD on Linux, macOS and Windows](https://github.com/partcad/partcad/actions/workflows/build.yml/badge.svg?event=schedule)](https://github.com/partcad/partcad/actions/workflows/build.yml?query=event%3Aschedule)
[![Deployment to PyPI](https://github.com/partcad/partcad/actions/workflows/deploy.yml/badge.svg)](https://github.com/partcad/partcad/actions/workflows/deploy.yml)
[![Documentation Status](https://readthedocs.org/projects/partcad/badge/?version=latest)](https://partcad.readthedocs.io/en/latest/?badge=latest)
<a href="https://discord.gg/h5qhbHtygj"><img alt="Discord" src="https://img.shields.io/discord/1308854595987968051?logo=discord&logoColor=white&label=Discord&labelColor=353c43&color=31c151"></a>

Browse [our documentation] and visit [our website]. Watch our 💥💥[demos](https://youtube.com/@PartCAD)💥💥.

## What is PartCAD?

[PartCAD] is the standard for documenting manufacturable physical products. It comes with a set of tools to maintain
product information and to facilitate efficient and effective workflows at all product lifecycle phases.

PartCAD is more than just a traditional CAD tool for drawing. In fact, it’s **not for drawing at all**. The letters
“CAD” in PartCAD stand for “computer-aided design” in a more generic sense, where “design” stands for the process of
getting from an idea to **a clear and deterministic specification of a manufacturable physical product** using a
computer (including the use of AI models). While PartCAD started as **the first package manager for hardware**, it is
now **the next-generation CAD** that can turn a single visionary individual into a one person corporation, or make one
future Product Manager as productive (**and much faster!**) as 10 corporate engineering departments of the past.

PartCAD is constantly evolving, with new features and integrations being added all the time.
**[Contact us](https://calendly.com/partcad-support/30min) to discuss how PartCAD can revolutionize your product
development process.**

## PartCAD packages

[PartCAD] includes tools to package product information:

- Optional (but highly recommended) high-level requirements (texts and drawings)
- Optional detailed design (mechanical outline, PCB schematics, software architecture)
- Implementation (mechanical CAD files, PCB layout, software artifacts)
- Optionally, the following data can be provided to augment or complement the output of PartCAD:

  - Additional manufacturing process requirements and instructions
  - Additional product validation instructions
  - Maintenance instructions

- Or any other product related metadata

Such packages are modular and reusable, allowing one to build not only on top of the CAD files of previous products, but
to build on top of their manufacturing processes as well.

## PartCAD outputs

As a result of maintaining the product information using PartCAD, the following outputs can be generated and, if
necessary, collected and managed using PartCAD tools:

- A product documentation (markdown, html or PDF)
- Design validation results
- Product bill of materials (mechanical, electrical, software)
- Sourcing information for all components
- Manufacturing process specification (including required equipment if any)
- Manufacturing instructions (sufficiently documented to be reproduced by anyone without inquiring any additional
  information)
- Product validation instructions
- Product validation results (given access to an experimental product and the required tools)
- Input data for software components to visualize the product on your website, with a 3D viewer, a configurator,
  manufacturing/assembly instructions and more

## Product development and testing

Once product information is packaged, it can be versioned and used for iterative improvements or to produce PartCAD
outputs either by human or AI actors. To achieve that, PartCAD integrates with third-party tools. Below are just some
examples of what third-party integrations can be used for:

- AI tools can be used to update the mechanical design and implementation based on the current state of the requirements
- A legacy CAD tool can be used manually to update the implementation
- AI tools can be used to validate the design and implementation to identify product requirement or best practices (e.g.
  to reduce manufacturing complexity) violations
- A web interface of an online store or an API of an additive manufacturer can be used to source and manufacture parts
- Simulation tools (potentially in conjunction with AI tools) can be used to validate that the product design matches
  the product requirements
- AI tools can be used to review the product implementation for correctness, safety or compliance
- Manufacturing processes are verified for completeness (e.g. tools requirements are specified for all operations)
- Manufacturing instructions are verified for correctness (e.g. the provided manufacturing steps can actually be
  successfully and safely performed, and fit within the capabilities of the selected manufacturing tools)

Some of the iterative improvements or tests can be achieved using PartCAD built-in features. However, the use of
third-party tools is recommended for unlocking cutting edge innovations and features.

## Operations using PartCAD

PartCAD also works on the following supplementary products to enable (if needed) operations without any use of
third-party tools:

- A CRM for part manufacturing and assembly shops for businesses of any size (from skilled individuals working in their
  garage to the biggest factories) to immediately start taking orders for manufacturable products maintained using
  PartCAD
- An inventory tool to manage the list of parts and final products in stock, as well as to track and manage all
  in-progress or completed orders, to immediately bring supply chains up and to scale them up while keeping all data
  private on-prem and not incurring any costs (for cloud services and alike)

## Supply Chains based on PartCAD

By letting the user easily switch between third-party engineering tools or manufacturers without having to migrate
product data, PartCAD creates a competitive environment for service providers to drive the costs down.

Whenever you select third-party tools (if any) to use in your workflows, you ultimately decide (and make it transparent
or auditable) how secure your supply chain is and how exposed your product information is. If you opt for on-prem tools
only, all your product information remains on-prem too. It makes PartCAD an ultimate solution for achieving data
sovereignty for those willing to keep their product data private. In the age of cloud data harvesting (especially for AI
training), it makes PartCAD a better alternative to any cloud-based PDM, PLM or BOM solution.

## Join us!

Stay informed and share feedback by joining [our Discord server](https://discord.gg/h5qhbHtygj). <br/>

Subscribe on [LinkedIn], [YouTube], [TikTok], [Facebook], [Instagram], [Threads] and [Twitter/X].

[![PartCAD Visual Studio Code extension](docs/source/images/vscode1.png)](https://marketplace.visualstudio.com/items?itemName=OpenVMP.partcad)

## Features

- Multiple OSes supported
  - [x] Windows
  - [x] Linux
  - [x] macOS
- Workflow acceleration by caching rendered models (including OpenSCAD, CadQuery and build123d)
  - [x] In memory
  - [x] On disk
  - [ ] Local Server _(in progress)_
  - [ ] Cloud _(in progress)_
- Collaboration on designs
  - [x] Versioning of CAD designs using `Git` _(like it's 2025 for real)_
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
    - [x] `BREP`
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
    - [x] `BREP`
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
[BREP]: https://en.wikipedia.org/wiki/Boundary_representation
[OpenCASCADE]: https://www.opencascade.com/
[Quick Start]: https://partcad.github.io/partcad/development/quick-start/
