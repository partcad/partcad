#!/bin/bash

CORES=$(lscpu -b -p=Core,Socket | grep -v "^#" | sort -u | wc -l)
# Clamp to [1, 4]: CPU detection can return 0/empty, which would pass -n 0 to pytest.
WORKERS=$(( CORES < 1 ? 1 : (CORES < 5 ? CORES : 4) ))
echo "Detected $CORES cores"
echo "Running tests with $WORKERS workers"

poetry run pytest partcad/tests -n "$WORKERS" -m "not slow" --timeout 300
rc=$?

if [ $rc -ne 0 ]; then
    echo "
Tests failed (pytest exited with $rc).

Please make sure all tests pass by debugging and fixing any errors before committing your changes.
Use the command below to run the same tests locally with $WORKERS workers and a 5 minute timeout:
    poetry run pytest partcad/tests -n $WORKERS -m \"not slow\" --timeout 300
"
    exit 1
fi
