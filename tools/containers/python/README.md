# Portable Python environment

This is a mocked integration container for PartCAD to run Python scripts inside a docker container if the user does not
have `miniforge3`, does not want to use `miniforge3`, of if for some reason the Python environments created by PartCAD
on the host OS are not working.

## How To

To run Python scripts inside the container, add the flag `--use-docker-python=true` in the command line:

```bash

pc --use-docker-python=true run my-script.py

```

## Build Instructions

To build the container, run the following command:

```bash
docker build -t partcad-integration-python -f tools/containers/python/Dockerfile tools/containers
```
