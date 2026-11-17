#!/bin/sh
# Renders an estate's pictures, and then its README: one picture at a time, since a furnished storey's models are
# memory enough for one render. Run by hand, where nothing is left out - the scenes declare 'timeout:', so the
# examples' CI sweep ('--fast-only') passes over them. What each picture is - of which object, from where, how large
# and of which of its links ('filter:') - is the 'render:' of the object pictured in the estate's partcad.yaml, as
# make_estate.py writes it; this only goes through them.
#
#   ./render_images.sh <estate>
set -e
cd "$1"
pc() { "${PC:-pc}" --no-ansi "$@"; }
# Every scene and sketch with a 'render:' of its own, in the order partcad.yaml declares them.
awk '/^[a-z]+:/ { kind = $1 } /^  [a-z0-9-]+:$/ { name = $1 } /^    render:$/ { print kind, name }' partcad.yaml |
    while read -r kind name; do
        case "$kind" in
        scenes:) pc render -S "${name%:}" ;;
        sketches:) pc render -s "${name%:}" ;;
        esac
    done
pc render -t readme
