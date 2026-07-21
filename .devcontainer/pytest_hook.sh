#!/bin/bash

CORES=$(lscpu -b -p=Core,Socket | grep -v "^#" | sort -u | wc -l)
WORKERS=$(( CORES < 5 ? CORES : 4 ))
echo "Detected $CORES cores"
echo "Running tests with $WORKERS workers"

poetry run pytest partcad/tests -n "$WORKERS" -m "not slow" --timeout 300
rc=$?

if [ $rc -ne 0 ]; then
    echo "
Tests failed (pytest exited with $rc).

Please make sure all tests pass by debugging and fixing any errors before committing your changes.
Use the command below to run all tests locally with $WORKERS workers and a 5 minute timeout:
    poetry run pytest partcad/tests -n $WORKERS --timeout 300
"
    exit 1
fi
