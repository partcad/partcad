#!/bin/sh
# Renders an estate's README images into <estate>/images, one at a time: a furnished storey's models are
# memory enough for one render. Run by hand, where nothing is left out - the scenes declare 'timeout:', so CI's
# '--fast-only' sweep does not render them. PNG size is a render option of the package, given for this run only.
#
#   ./render_images.sh <estate> [storey]     # the storey its README pictures (make_estate.py's 'picture'), 1 by default
set -e
storey="${2:-1}"
cd "$1"
cp partcad.yaml partcad.yaml.orig
trap 'mv partcad.yaml.orig partcad.yaml' EXIT
printf '  png:\n    width: 1600\n    height: 1000\n' >> partcad.yaml
mkdir -p images
pc() { "${PC:-pc}" --no-ansi render -t png --style shaded -O images "$@"; }
pc --view iso -S outside
pc --view iso shell
pc --view top -S "storey-$storey"
mv "images/storey-$storey.png" "images/plan-$storey.png"
pc --view iso -S "storey-$storey"
