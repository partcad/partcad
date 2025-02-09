#!/bin/bash

CORES=$(lscpu -b -p=Core,Socket | grep -v "^#" | sort -u | wc -l)
echo "Detected $CORES cores"

# The maximum optimal number of workers to use for running the tests
# efficiently in parallel withoug overloading the system
MAX_WORKERS=4
WORKERS=$(( CORES <= MAX_WORKERS ? CORES : MAX_WORKERS ))
echo "Running tests with $WORKERS workers"
poetry run behavex features --parallel-processes=$WORKERS --parallel-scheme=feature
