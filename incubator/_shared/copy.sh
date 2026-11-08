#!/usr/bin/env bash
#
# Copies the shared part of the distributor plugins into every package beside
# it, and writes the digest each package's tests hold its copy to.
#
set -euo pipefail

here="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "${here}/.."

for package in partcad-svc-commerce-*/; do
	package="${package%/}"
	for file in distributor.py conftest.py test_distributor.py; do
		cp "${here}/${file}" "${package}/${file}"
	done
	(cd "${package}" && sha256sum distributor.py >distributor.sha256)
	echo "${package}: $(cut -c1-12 "${package}/distributor.sha256")"
done
