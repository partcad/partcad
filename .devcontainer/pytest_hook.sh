#!/bin/bash

# One pytest-xdist worker per physical core -- not per logical CPU, which is
# what the CI jobs use: a commit is made on a machine somebody is also working
# on, and the hyperthreads are left to them. Each (Core,Socket) pair lscpu lists
# is one physical core, however many threads it runs.
#
# There used to be a ceiling of four on top of this. Set PC_PYTEST_WORKERS to
# choose the number yourself -- fewer on a machine short of memory, since every
# worker starts sandbox interpreters of its own. More workers stop helping well
# before a big machine runs out of cores: on a 24-core one this hook took about
# four minutes on 4, 8 and 24 workers alike, its tests taking longer each the
# more of them ran at once.
CORES=$(lscpu -b -p=Core,Socket 2>/dev/null | grep -v "^#" | sort -u | wc -l)
# At least one: CPU detection can return 0/empty, which would pass -n 0 to pytest.
WORKERS="${PC_PYTEST_WORKERS:-$(( CORES < 1 ? 1 : CORES ))}"
echo "Detected $CORES physical cores"
echo "Running tests with $WORKERS workers"

# How long one test may take before it is called a hang.
#
# This is a hang detector and nothing else, so it has to clear the slowest thing
# a passing test legitimately does - and for this suite that is not the test, it
# is the CAD sandbox underneath it. A test whose part is scripted (build123d,
# CadQuery, SDF, OpenSCAD) runs in a managed Python environment that PartCAD
# provisions on first use: a fresh interpreter plus a pip install of the CAD
# stack, minutes of work, paid once and then cached in ~/.partcad. Whichever
# test happens to be the first to need a given sandbox pays for it.
#
# The budget is per test, so a warm cache never comes near it and raising it
# does not slow a passing run down; what it buys is a gate that reports the
# commit rather than the state of the cache. A genuine hang is still caught,
# 15 minutes later.
#
# It is not what keeps a gate from failing on a different test each run -- that
# is 'pass_filenames: false' in dev-tools/pre-commit-config.yaml, without which
# 'pre-commit' runs this hook once per partition of the staged file list, several
# whole suites at once over one working tree. This budget only ever hid how slow
# those runs made each other.
#
# Override it for a slower machine, or lower it deliberately when hunting one:
#   PC_PYTEST_TIMEOUT=1800 git commit ...
TIMEOUT="${PC_PYTEST_TIMEOUT:-900}"

# pytest has been observed to exit 0 despite failures on some platforms (Windows
# in particular), so the exit code alone cannot be trusted. Instead the pytest
# session writes an explicit verdict to a marker file (see 'conftest.py' at the
# repository root, which is also where the "Pytest" job in
# '.github/workflows/test.yml' reads its verdict from), and this hook reads that.
# The marker path carries this shell's PID so concurrent hook runs never collide,
# lives under a temp dir rather than in the repo, and is removed both before and
# after the run so nothing is left behind.
MARKER="${TMPDIR:-/tmp}/partcad-pytest-result-$$"
export PYTEST_RESULT_MARKER="$MARKER"
rm -f "$MARKER"

# One definition of the run, so that what is executed and what the failure
# message tells the user to execute cannot drift apart.
#
# The paths are the ones the "Pytest" job in '.github/workflows/test.yml' runs.
# This used to be 'tests/partcad' alone, so a change to the CLI, the client, the
# daemon, the shared utilities or the FreeCAD addon was committed without any of
# their tests having run. They are some 2,400 tests more, nearly all of them fast.
PYTEST_ARGS=(tests cad/freecad -n "$WORKERS" -m "not slow" --timeout "$TIMEOUT")

poetry run pytest "${PYTEST_ARGS[@]}"
rc=$?

result=$(cat "$MARKER" 2>/dev/null)
rm -f "$MARKER"

if [ "$result" != "success" ]; then
    echo "
Tests did not pass (pytest exit code $rc, recorded result '${result:-none}').

Please make sure all tests pass by debugging and fixing any errors before committing your changes.
Use the command below to run the same tests locally:"
    # '%q' per element rather than "${PYTEST_ARGS[*]}": the marker expression is
    # one argument here ('not slow'), and joining the array unquoted prints it as
    # two words, so what the message offers to be copied is not what was run.
    printf '    poetry run pytest'
    printf ' %q' "${PYTEST_ARGS[@]}"
    printf '\n'
    echo "
A first run on a cold cache is slow: every scripted part builds its CAD sandbox
before it can be rendered. If a test was reported as timing out, run it again
before looking for a bug in it - the sandbox it waited for is now built.
"
    exit 1
fi
