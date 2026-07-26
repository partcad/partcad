#!/bin/bash

# Clamp to [1, 4]: os.cpu_count() can come back as None, and past four workers
# the scenarios contend for CPU and for their state directory copies more than
# the extra parallelism buys back.
WORKERS=$(poetry run python -c "import os; print(min(4, os.cpu_count() or 1))")
echo "Running tests with $WORKERS workers"

# Warm the shared PartCAD state directory before any worker starts. Without
# this each scenario would re-clone //pub and rebuild the conda sandbox in its
# own private $HOME. Already-seeded runs return immediately.
poetry run python -m features.seed || exit 1

# behavex is configured separately from behave and ignores the "tags" setting
# in behave.ini, so the exclusions that file applies have to be repeated here
# or the @ai scenarios silently start running. behavex contributes ~@WIP itself.
poetry run behavex features -t '~@ai' --parallel-processes="$WORKERS" --parallel-scheme=feature
