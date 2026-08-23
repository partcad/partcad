#!/bin/sh
#
# PartCAD, 2026
#
# Licensed under Apache License, Version 2.0.
#
# Generate "platforms.json", the release manifest that says which platform
# builds a release actually carries.
#
# Three clients download a standalone bundle from a GitHub release --
# "partcad_client.selfupdate" (`pc upgrade`), the VS Code extension
# ("src/common/provision.ts") and the FreeCAD addon
# ("partcad_freecad/provision.py") -- and none of them can see a release before
# it exists. They used to construct the archive name from the host alone, which
# stopped working the moment the bundles were named after the OS *version* they
# were frozen on ("ubuntu-24.04-x86_64", not "linux-x86_64"). There is no
# host-only answer to that: which builds exist is a property of the release, so
# the release has to say.
#
# The manifest is therefore generated from the archives that are about to be
# uploaded, never from a list kept somewhere by hand -- a second copy of the
# platform list is exactly the thing that drifts.
#
#   {
#     "version": "0.7.177",
#     "bundle": {
#       "linux": {"x86_64": ["ubuntu-24.04-x86_64", "ubuntu-22.04-x86_64"]},
#       ...
#     },
#     "ide": {"linux": {"x86_64": ["linux-x86_64"]}, ...}
#   }
#
# Each list is ordered newest build first, the same order "install.sh" keeps in
# LINUX_BUILDS/MACOS_BUILDS. It is an order, not an answer: a client still drops
# the builds newer than the machine it runs on (a frozen bundle needs the C
# library of the machine that froze it, or newer), and a client that cannot
# identify its host release walks the list backwards -- oldest build first,
# which is the most portable one. That policy lives in the clients, next to the
# host detection it depends on; only the inventory lives here.
#
# Usage:
#   platforms-manifest.sh --bundles <dir> --ide <dir> [--output <file>]
#
# Both directories are the ones "deploy.yml" downloads the release artifacts
# into. The ".dmg"/"-setup.exe" installers beside the IDE archives are ignored,
# as are the ".sha256" files: what a client downloads is the archive.

set -eu

BUNDLE_DIR=""
IDE_DIR=""
OUTPUT=""

fail() {
  echo "platforms-manifest.sh: $*" >&2
  exit 1
}

while [ $# -gt 0 ]; do
  case "$1" in
  --bundles)
    BUNDLE_DIR="${2:-}"
    shift 2
    ;;
  --ide)
    IDE_DIR="${2:-}"
    shift 2
    ;;
  --output)
    OUTPUT="${2:-}"
    shift 2
    ;;
  -h | --help)
    sed -n '8,46p' "$0"
    exit 0
    ;;
  *) fail "unknown argument '$1'" ;;
  esac
done

[ -n "${BUNDLE_DIR}" ] || fail "--bundles <dir> is required"
[ -n "${IDE_DIR}" ] || fail "--ide <dir> is required"
[ -d "${BUNDLE_DIR}" ] || fail "no such directory: ${BUNDLE_DIR}"
[ -d "${IDE_DIR}" ] || fail "no such directory: ${IDE_DIR}"

# "<kind> <version> <platform-id>" for every release archive in a directory.
# The prefix is what the archive name starts with, so that the IDE's
# "partcad-ide-<version>-<platform>" is not read as a "partcad" bundle whose
# version is "ide".
scan() {
  scan_kind="$1"
  scan_dir="$2"
  scan_prefix="$3"
  find "${scan_dir}" -type f \( -name "${scan_prefix}-*.tar.gz" -o -name "${scan_prefix}-*.zip" \) |
    while IFS= read -r scan_path; do
      scan_name="${scan_path##*/}"
      scan_name="${scan_name%.tar.gz}"
      scan_name="${scan_name%.zip}"
      scan_rest="${scan_name#${scan_prefix}-}"
      # "<version>-<platform-id>". A version carries no dash of its own.
      scan_version="${scan_rest%%-*}"
      scan_id="${scan_rest#*-}"
      [ "${scan_version}" != "${scan_rest}" ] || continue
      # Anything whose second field is not a version is not this kind's archive:
      # "partcad-ide-<version>-..." matches the bundle prefix too, and the two
      # kinds are only in separate directories by convention.
      case "${scan_version}" in
      [0-9]*) ;;
      *) continue ;;
      esac
      printf '%s %s %s\n' "${scan_kind}" "${scan_version}" "${scan_id}"
    done
}

ROWS="$(
  scan bundle "${BUNDLE_DIR}" partcad
  scan ide "${IDE_DIR}" partcad-ide
)"

[ -n "${ROWS}" ] || fail "found no release archives in '${BUNDLE_DIR}' or '${IDE_DIR}'"

# One release publishes one version; anything else means the artifacts of two
# runs were mixed, and a manifest naming one of them would be a lie.
VERSIONS="$(printf '%s\n' "${ROWS}" | awk '{print $2}' | sort -u)"
if [ "$(printf '%s\n' "${VERSIONS}" | wc -l)" -ne 1 ]; then
  fail "the archives carry more than one version: $(printf '%s' "${VERSIONS}" | tr '\n' ' ')"
fi

MANIFEST="$(
  printf '%s\n' "${ROWS}" | LC_ALL=C awk -v version="${VERSIONS}" '
    # A build is named after the image it was frozen on; a client asks by
    # operating system. "ubuntu" is the only Linux builder, and the id is not a
    # statement that the bundle needs Ubuntu -- see the note in "install.sh".
    function osname(name) {
      if (name == "ubuntu" || name == "linux") return "linux"
      if (name == "macos") return "macos"
      if (name == "windows") return "windows"
      return ""
    }
    # A sortable key for a dotted version: "24.04" -> "00024.00004...".
    # Comparing the versions themselves as strings would put "9" after "24",
    # and shell arithmetic would read the leading zero of "04" as octal.
    function vkey(v,   i, m, f, out) {
      m = split(v, f, ".")
      out = ""
      for (i = 1; i <= 4; i++) out = out sprintf("%05d.", (i <= m) ? f[i] + 0 : 0)
      return out
    }
    {
      kind = $1
      id = $3
      # "ubuntu-24.04-x86_64" -> name "ubuntu", release version "24.04", arch
      # "x86_64"; "linux-x86_64" (the IDE, built once per operating system and
      # architecture) -> name "linux", no release version, arch "x86_64".
      n = split(id, part, "-")
      if (n != 2 && n != 3) { print "unrecognized platform id: " id > "/dev/stderr"; bad = 1; next }
      name = part[1]
      arch = part[n]
      relver = (n == 3) ? part[2] : ""
      os = osname(name)
      if (os == "") { print "unrecognized operating system: " id > "/dev/stderr"; bad = 1; next }
      if (arch != "x86_64" && arch != "arm64") { print "unrecognized architecture: " id > "/dev/stderr"; bad = 1; next }
      key = kind SUBSEP os SUBSEP arch
      if (index(entries[key], " " id "\n")) next  # the same build in .tar.gz and .zip
      entries[key] = entries[key] vkey(relver) " " id "\n"
      kinds[kind] = 1
    }
    END {
      if (bad) exit 1
      # Fixed orders, so that two runs of this script over the same release
      # produce byte-identical JSON.
      split("bundle ide", kind_order, " ")
      split("linux macos windows", os_order, " ")
      split("x86_64 arm64", arch_order, " ")
      out = sprintf("{\n  \"version\": \"%s\"", version)
      for (ki = 1; ki <= 2; ki++) {
        kind = kind_order[ki]
        if (!(kind in kinds)) continue
        kind_out = ""
        for (oi = 1; oi <= 3; oi++) {
          os = os_order[oi]
          os_out = ""
          for (ai = 1; ai <= 2; ai++) {
            arch = arch_order[ai]
            key = kind SUBSEP os SUBSEP arch
            if (!(key in entries)) continue
            count = split(entries[key], rows, "\n")
            n = 0
            for (i = 1; i <= count; i++) if (rows[i] != "") sorted[++n] = rows[i]
            # Insertion sort on the version key, newest build first.
            for (i = 2; i <= n; i++) {
              cur = sorted[i]
              for (j = i - 1; j >= 1 && sorted[j] < cur; j--) sorted[j + 1] = sorted[j]
              sorted[j + 1] = cur
            }
            list = ""
            for (i = 1; i <= n; i++) {
              sub(/^[^ ]* /, "", sorted[i])
              list = list (i == 1 ? "" : ", ") "\"" sorted[i] "\""
              delete sorted[i]
            }
            os_out = os_out (os_out == "" ? "" : ",") sprintf("\n      \"%s\": [%s]", arch, list)
          }
          if (os_out == "") continue
          kind_out = kind_out (kind_out == "" ? "" : ",") sprintf("\n    \"%s\": {%s\n    }", os, os_out)
        }
        out = out sprintf(",\n  \"%s\": {%s\n  }", kind, kind_out)
      }
      printf "%s\n}\n", out
    }
  '
)"

if [ -n "${OUTPUT}" ]; then
  printf '%s\n' "${MANIFEST}" >"${OUTPUT}"
else
  printf '%s\n' "${MANIFEST}"
fi
