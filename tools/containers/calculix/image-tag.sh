#!/usr/bin/env bash
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# The tag the CalculiX runtime image is published under: what is in it, not what
# version of PartCAD built it.
#
# The other images here are tagged with PartCAD's version, which works because
# the code that pulls them ships in the same wheel and can name that version.
# This one is pulled by a *plugin*, in its own repository on its own schedule
# (`//pub/feature/cae/calculix`, which declares `container:` in its
# `partcad.yaml`), and a plugin cannot know what PartCAD's version will be.
#
# A content tag answers that and one more thing. It is immutable: a tag that
# exists never changes, so a plugin that pinned one keeps working after this
# image is next edited, and a branch that edits the image publishes a *new* tag
# rather than replacing what everything else is using. It also means a branch
# and the merge of that branch build the same tag, so nothing has to be
# re-pinned when it lands.
#
# Run it to find out what to pin:
#
#     tools/containers/calculix/image-tag.sh
#
# Everything the image is built from goes into the hash. `Dockerfile` and
# `verify.py` are obvious; `_common/pc-container-json-rpc.py` is what the image
# runs as its entry point, so a change there is a different runtime with the
# same recipe.
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

cat \
  "$here/Dockerfile" \
  "$here/verify.py" \
  "$here/../_common/pc-container-json-rpc.py" \
  | sha256sum | cut -c1-12
