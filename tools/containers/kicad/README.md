# PartCAD integration with KiCad

The official website: [KiCad.org](https://kicad.org/)

## Intro

KiCad can be used to model PCBs. PartCAD can be used to package and version KiCad project files just like any other
design files.

NOTE: If you happen to have KiCad installed on your machine, you can use the `--use-docker-kicad=false` flag to run the
KiCad locally.

The same image is what `pc open --with kicad` -- the "Open in KiCad" item in the VS Code extension's context menu for a
`kicad` part -- falls back to when the machine has no KiCad of its own. It is the same container either way: this image
is `kicad/kicad` with PartCAD's environment on top, so it carries the GUI as well as `kicad-cli`, and there is one
KiCad container in the product rather than two. A `kicad` part points at the STEP file `kicad-cli` writes out of the
board, so what actually gets opened is the `.kicad_pro`, `.kicad_pcb` or `.kicad_sch` beside it (see `KICAD` in
`partcad_client.external`).

## How To

To add parts designed in KiCad, use the the part type `kicad` in the `partcad.yaml` file.

```yaml
parts:
  my-pcb:
    type: kicad
```

## Platforms

The sandbox is **linux/amd64 only**, and so is everything PartCAD builds it out
of:

* `kicad/kicad`, the base image, is published for `linux/amd64` alone -- the
  `9.0` manifest list holds that one platform, and `8.0` (what this Dockerfile
  pins) is a single-architecture manifest;
* this Dockerfile then installs the `x86_64` Miniforge build by name.

There is therefore no image to pull on an Arm host, and nothing to run if there
were. It is also why `ghcr.io/partcad/partcad-container-kicad` is built by one
`amd64` CI job rather than as a multi-platform image.

KiCad itself is another matter: it ships Arm builds for macOS and Linux
distributions package it for arm64, so a user who has `kicad-cli` installed can
run it directly with `useDockerKicad: false` (or the `useDocker` master switch
over it) and build a `kicad` part on Arm perfectly well.

The KiCad example says exactly that, in the two things the context knows about
-- what the machine is, and how PartCAD is configured to work (see "Tags" in the
configuration documentation):

```yaml
unless: [[arm, useDocker, useDockerKicad]]
```

All three have to hold together: an Arm machine, *and* Docker in use, *and*
Docker in use for KiCad. Where they do, the container is what would be reached
for and there is none to reach for, so the package is skipped with a line saying
so instead of failing at use. Where the container has been turned off, nothing
is excluded and the native `kicad-cli` is used as it is anywhere else.

## Current Status

The manufacturability of the PCBs is only implemented through the providers of type `store`. This means that the vendor
and sku need to be specified in the `partcad.yaml` file.

```yaml
parts:
  my-pcb:
    type: kicad
    vendor: pcbvendor1
    sku: 123456

# The below is optional and only intended to demonstrate the usage of a `store`
suppliers:
  - storeProvider1

providers:
  storeProvider1:
    type: store
    ...
```

The manufacturability test of the PCBs using a `manufacturer` and the manufacturing methods starting with `pcb` is not
implemented yet.

````yaml
parts:
  my-pcb:
    type: kicad
    manufacturing:
      method: pcbBasic

# The below is optional and only intended to demonstrate the usage of a `manufacturer`
suppliers:
  - pcbManufacturingProvider1

providers:
  pcbManufacturingProvider1:
    type: manufacturer
    ...

```


## Build Instructions

To build the container, run the following command:

```bash
docker build -t partcad-integration-kicad -f tools/containers/kicad/Dockerfile tools/containers
````
