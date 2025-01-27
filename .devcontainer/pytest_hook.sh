#!/bin/bash

CORES=$(lscpu -b -p=Core,Socket | grep -v "^#" | sort -u | wc -l)
echo "Detected $CORES cores"
echo "Running tests with $(( CORES < 5 ? CORES : 4 )) workers"
poetry run pytest partcad/tests -n $(( CORES < 5 ? CORES : 4 )) -m "not slow" --timeout 300

if [ -f .pytest_success ]; then
    rm .pytest_success
else
    echo "
No successful test run detected.

Please make sure all tests pass by debugging and fixing any errors before committing your changes.
Use the command below to run all tests locally with 4 workers and a 5 minute timeout:
    poetry run pytest partcad/tests -n 4 --timeout 300
"
    exit 1
fi
