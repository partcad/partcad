#!/usr/bin/env bash
#
# Refresh the documentation translation catalogs.
#
# English (docs/source/*.rst) is the single source of truth. This script
# extracts the translatable strings into gettext templates and merges them into
# the per-language .po catalogs under docs/source/locales/<lang>/LC_MESSAGES/.
#
# Run it whenever the English docs change. New strings are added, edited strings
# are marked "#, fuzzy" for re-translation, and obsolete ones are commented out;
# existing translations are preserved. Translators then edit the .po files only.
#
# Code blocks, command examples, and CLI output are intentionally NOT extracted
# (see gettext_additional_targets in conf.py), so the translated docs keep
# documenting the English application interface.
#
# Usage (from the repo root, inside the dev container):
#   poetry run bash docs/update-translations.sh
#
set -euo pipefail

# Languages to maintain. These must match the Read the Docs project language
# codes and the locales/<lang> directory names exactly.
LANGUAGES=(de es ru zh_CN)

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SOURCE_DIR="${SCRIPT_DIR}/source"
POT_DIR="${SCRIPT_DIR}/build/gettext"   # gitignored (docs/build)
LOCALE_DIR="${SOURCE_DIR}/locales"

echo ">> Extracting translatable strings to ${POT_DIR}"
sphinx-build -b gettext "${SOURCE_DIR}" "${POT_DIR}"

echo ">> Updating .po catalogs in ${LOCALE_DIR}"
lang_args=()
for lang in "${LANGUAGES[@]}"; do
  lang_args+=(-l "${lang}")
done
sphinx-intl update -p "${POT_DIR}" -d "${LOCALE_DIR}" "${lang_args[@]}"

echo ">> Done. Review and translate the updated .po files, then commit them."
