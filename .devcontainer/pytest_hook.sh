#!/bin/bash

CORES=$(lscpu -b -p=Core,Socket | grep -v "^#" | sort -u | wc -l)
# Clamp to [1, 4]: CPU detection can return 0/empty, which would pass -n 0 to pytest.
WORKERS=$(( CORES < 1 ? 1 : (CORES < 5 ? CORES : 4) ))
echo "Detected $CORES cores"
echo "Running tests with $WORKERS workers"

# pytest has been observed to exit 0 despite failures on some platforms (Windows
# in particular), so the exit code alone cannot be trusted. Instead the pytest
# session writes an explicit verdict to a marker file (see conftest.py), and this
# hook reads that. The marker path carries this shell's PID so concurrent hook
# runs never collide, lives under a temp dir rather than in the repo, and is
# removed both before and after the run so nothing is left behind.
MARKER="${TMPDIR:-/tmp}/partcad-pytest-result-$$"
export PYTEST_RESULT_MARKER="$MARKER"
rm -f "$MARKER"

poetry run pytest partcad/tests -n "$WORKERS" -m "not slow" --timeout 300
rc=$?

result=$(cat "$MARKER" 2>/dev/null)
rm -f "$MARKER"

if [ "$result" != "success" ]; then
    echo "
Tests did not pass (pytest exit code $rc, recorded result '${result:-none}').

Please make sure all tests pass by debugging and fixing any errors before committing your changes.
Use the command below to run the same tests locally with $WORKERS workers and a 5 minute timeout:
    poetry run pytest partcad/tests -n $WORKERS -m \"not slow\" --timeout 300
"
    exit 1
fi
