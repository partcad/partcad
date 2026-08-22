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

# Worth knowing, and deliberately not acted on here: behavex is configured
# separately from behave and ignores the "tags" setting in behave.ini, so this
# runs the @ai scenarios that `behave` on its own would exclude. Passing
# -t '~@ai' would match behave.ini's intent, but it would also stop running
# scenarios that run today, and narrowing what gets tested is not this change's
# business. Add it deliberately, as its own change, if that is what you want.
poetry run behavex features --parallel-processes="$WORKERS" --parallel-scheme=feature
