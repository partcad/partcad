# PartCAD integration with KiCad

The official website: [KiCad.org](https://kicad.org/)

## Intro

KiCad can be used to model PCBs. PartCAD can be used to package and version KiCad project files just like any other
design files.

NOTE: If you happen to have KiCad installed on your machine, you can use the `--use-docker-kicad=false` flag to run the
KiCad locally.

## How To

To add parts designed in KiCad, use the the part type `kicad` in the `partcad.yaml` file.

```yaml
parts:
  my-pcb:
    type: kicad
```

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
