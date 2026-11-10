#!/usr/bin/env bash
#
# Copies the shared part of the distributor plugins into every package beside
# it, and into every directory named on the command line (the checkout of a
# package that has a repository of its own already), and writes the digest each
# package's tests hold its copy to.
#
#   incubator/_shared/copy.sh ../partcad-svc-commerce-digikey ../partcad-svc-commerce-octopart
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

targets=()
for package in "${here}"/../partcad-svc-commerce-*/; do
	[ -d "${package}" ] && targets+=("${package%/}")
done
for package in "$@"; do
	targets+=("$(cd "${package}" && pwd)")
done

for package in "${targets[@]}"; do
	for file in distributor.py conftest.py test_distributor.py; do
		cp "${here}/${file}" "${package}/${file}"
	done
	# sha256sum is GNU coreutils; macOS has shasum. Both write "<digest>  <file>".
	if command -v sha256sum >/dev/null 2>&1; then
		(cd "${package}" && sha256sum distributor.py >distributor.sha256)
	else
		(cd "${package}" && shasum -a 256 distributor.py >distributor.sha256)
	fi
	echo "$(basename "${package}"): $(cut -c1-12 "${package}/distributor.sha256")"
done
