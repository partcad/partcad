#!/usr/bin/env bash
#
# Materialize the symlink-based Claude plugin (ai-agents/claude) into a
# self-contained, SYMLINK-FREE artifact suitable for cross-platform
# distribution.
#
# Why: the in-repo plugin shares its skills with ai-agents/common/skills via a
# symlink. That is convenient for local use and works for macOS/Linux installs,
# but git may not preserve symlinks on Windows checkouts, which would ship an
# empty plugin. This script dereferences the symlink into real files so the
# published artifact contains no symlinks at all.
#
# Requires no credentials. `claude plugin validate` runs fully offline.
#
# Usage:
#   ai-agents/scripts/materialize.sh [OUT_DIR]
#
# Produces (default OUT_DIR = ai-agents/.build/marketplace):
#   OUT_DIR/.claude-plugin/marketplace.json   catalog, source ./pc
#   OUT_DIR/pc/.claude-plugin/plugin.json     the plugin manifest
#   OUT_DIR/pc/skills/<name>/SKILL.md         real files (no symlinks)
#   OUT_DIR/pc-<version>.zip                  plugin archive (`zip` required)
#
# The archive carries the version, like every other asset on a PartCAD release,
# and that version is the repository's: "dev-tools/bumpversion.toml" moves
# "plugin.json" with everything else, so the plugin published by a release
# states the release that published it.

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "$SCRIPT_DIR/../.." && pwd)"

PLUGIN_NAME="pc"
PLUGIN_SRC="$ROOT/ai-agents/claude"
OUT_DIR="${1:-$ROOT/ai-agents/.build/marketplace}"

if [ ! -f "$PLUGIN_SRC/.claude-plugin/plugin.json" ]; then
  echo "ERROR: plugin manifest not found at $PLUGIN_SRC/.claude-plugin/plugin.json" >&2
  exit 1
fi

# Read with `sed` rather than `jq`, `node` or `python3`: this script runs on a
# contributor's machine as readily as on a runner, and the only things it needs
# so far are `cp`, `find` and `zip`.
PLUGIN_VERSION="$(sed -n 's/.*"version"[[:space:]]*:[[:space:]]*"\([^"]*\)".*/\1/p' \
  "$PLUGIN_SRC/.claude-plugin/plugin.json" | head -n 1)"
if [ -z "$PLUGIN_VERSION" ]; then
  echo "ERROR: no version in $PLUGIN_SRC/.claude-plugin/plugin.json" >&2
  exit 1
fi

echo "==> Materializing $PLUGIN_SRC -> $OUT_DIR/$PLUGIN_NAME (dereferencing symlinks)"
rm -rf "$OUT_DIR"
mkdir -p "$OUT_DIR/.claude-plugin"

# -R recursive, -L dereference every symlink into real files.
cp -RL "$PLUGIN_SRC" "$OUT_DIR/$PLUGIN_NAME"

# Hard guarantee for Windows: the artifact must contain zero symlinks.
remaining="$(find "$OUT_DIR" -type l -print)"
if [ -n "$remaining" ]; then
  echo "ERROR: symlinks remain in the materialized artifact:" >&2
  echo "$remaining" >&2
  exit 1
fi

# Sanity: at least one skill must have come through the dereference.
if ! find "$OUT_DIR/$PLUGIN_NAME/skills" -name SKILL.md -print -quit | grep -q .; then
  echo "ERROR: no SKILL.md found under the materialized plugin" >&2
  exit 1
fi

# Emit a marketplace catalog whose plugin source is the self-contained copy.
cat > "$OUT_DIR/.claude-plugin/marketplace.json" <<JSON
{
  "\$schema": "https://anthropic.com/claude-code/marketplace.schema.json",
  "name": "partcad",
  "description": "PartCAD skills for AI coding agents",
  "owner": {
    "name": "Roman Kuzmenko",
    "email": "rkuz@partcad.org"
  },
  "plugins": [
    {
      "name": "$PLUGIN_NAME",
      "description": "Mechanical and robotics engineering with PartCAD",
      "source": "./$PLUGIN_NAME"
    }
  ]
}
JSON

echo "==> Validating materialized marketplace"
claude plugin validate "$OUT_DIR"

# And the plugin itself, which is the half that has never been checked. Run
# against "ai-agents/claude" the same command reads nothing at all -- component
# directories are not read through symlinks, and "skills" there is one -- so it
# warns and passes over a "SKILL.md" with no front matter. Here the files are
# real, so this is the first time anything looks at them.
echo "==> Validating materialized plugin"
claude plugin validate "$OUT_DIR/$PLUGIN_NAME"

# The archive is a required output, not a bonus. It used to be written only
# "if command -v zip", which was harmless while nothing read it; the release
# attaches it now, and the workflow that builds it fails on a missing *file*.
# So a machine without "zip" reported "no files found" from an upload step
# several steps later, naming neither the tool nor this script.
if ! command -v zip >/dev/null 2>&1; then
  echo "ERROR: 'zip' is required to write $PLUGIN_NAME-$PLUGIN_VERSION.zip. Install it and run again." >&2
  exit 1
fi

ARCHIVE="$PLUGIN_NAME-$PLUGIN_VERSION.zip"
( cd "$OUT_DIR" && rm -f "$ARCHIVE" && zip -qr "$ARCHIVE" "$PLUGIN_NAME" )
echo "==> Wrote plugin archive: $OUT_DIR/$ARCHIVE"

echo "==> Done. Symlink-free artifact at: $OUT_DIR ($PLUGIN_NAME $PLUGIN_VERSION)"
