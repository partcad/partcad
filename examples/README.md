# PartCAD Examples

## Publish (produce) models

There are many ways to produce a PartCAD model that can be consumed by others.

- Create and use 2D blueprints (sketches):

  - [Primitive sketches](./produce_sketch_basic/)
  - [DXF files](./produce_sketch_dxf/)
  - [SVG files](./produce_sketch_svg/)
  - [CadQuery scripts](./produce_sketch_cadquery/)
  - [Build123d scripts](./produce_sketch_build123d/)
  - [Parts (3D shapes) using 2D sketch and extrude](./produce_part_extrude/)
  - [Parts (3D shapes) using 2D sketch and sweep](./produce_part_sweep/)

- Import parts defined using Python CAD frameworks:

  - [Primitive shapes using CadQuery](./produce_part_cadquery_primitive/)
  - [PartCAD logo using CadQuery](./produce_part_cadquery_logo/)
  - [Primitive shapes using build123d](./produce_part_build123d_primitive/)

- Import parts defined using CAD scripting languages:

  - [Primitive shapes using OpenSCAD](./produce_part_openscad/)
  - [Primitive shapes using Chili3D](./produce_part_chili3d_primitive/)
  - [Shapes defined by signed distance functions (SDF)](./produce_part_sdf/)

- Import parts defined using CAD Files:
  - [STEP files](./produce_part_step/)
  - [BREP files](./produce_part_brep/)
  - [STL files](./produce_part_stl/)
  - [3MF files](./produce_part_3mf/)
  - [OBJ files](./produce_part_obj/)
  - [KiCad PCBs](./produce_part_kicad/)

- Combine parts into assemblies:
  - [Assembly YAML (ASSY) files](./produce_assembly_assy/)
  - [URDF files](./produce_assembly_urdf/)

- Place objects into scenes (where things are, not how they got there):
  - [Assembly YAML (ASSY) files and Gazebo world files](./produce_scene_assy/)

- Ship software with the hardware:
  - [Firmware images and other files a product ships with](./produce_software/)

## Get (consume) existing models

Below are some examples of consuming existing modules:

- Python scripts that use CadQuery:

  - [Import PartCAD parts in CadQuery scripts](./consume_cadquery/)

- Python scripts that use build123d:

  - [Import PartCAD parts in build123d scripts](./consume_build123d/)

- Any other Python script:
  - [Import PartCAD parts in Python scripts](./consume_standalone/)

## Misc Features

These examples showcase particular PartCAD features:

- [Render 2D projections, and configure each of them on its own](./feature_render)
- [Technical drawings, from a render implementation another package supplies](./feature_render_custom)
- [Export to 3D and CAD files](./feature_export)
- [Export parameters, and an export implementation of one's own](./feature_export_custom)
- [Convert parts inside a package or standalone (ad-hoc)](./feature_convert_part)
- [Convert sketch inside a package or standalone (ad-hoc)](./feature_convert_sketch)
- [Import parts or assemblies (with optional format conversion)](./feature_import)
- [Interfaces and mating](./feature_interface)
- [Simulate a part or an assembly, and validate what happened](./feature_simulate)
- [Part enrichment](./feature_enrich)
- [Parts built by a part type the package defines itself](./produce_part_wrapper)
- [Mono-repo and Multi-repo](./feature_monorepo)

## External integrations

### Repositories with Existing Part Designs

PartCAD uses `plugins` to integrate with external repositories of part designs.

- [PartCAD parts from a CSV file](./plugin_repository_basic/)
- [External repository with multiple packages](./plugin_repository_tree/)
- [Fully featured external repository](./plugin_repository_full/)

The integrations to external repositories can't be accessed explicitly. They can only be used implicitly when a
reference to packages from this repository is used. Examples of such packages can be found in `//pub/ext`.

```bash
pc init
pc list packages -r //pub/ext
```

### Supply Chain

PartCAD uses `providers` to implement supply chain operations. Below are some examples of part providers:

- [Buy off-the-shelf parts by SKU (provider of the type "store")](./provider_store/)
- [Manufacture parts following given instructions (provider of the type "manufacturer")](./provider_manufacturer/)

The existing providers in PartCAD's public repository can be listed using the following command:

```bash
pc init
pc list providers -r //pub/svc/commerce
```
