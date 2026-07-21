#!/usr/bin/env bash
#
# Create a conda environment, retrying transient package corruption.
#
# conda-forge downloads intermittently land corrupted and mamba aborts the whole
# job with "Found incorrect download: <pkg>" / "<pkg>.tar.bz2 extraction
# failed". The upstream packages are fine on a refetch, so drop the cached
# tarballs and try again rather than losing the run to a bad download.
#
# Usage: mamba-create-retry.sh -n <env> [packages...]
set -euo pipefail

attempts="${MAMBA_CREATE_ATTEMPTS:-3}"

for attempt in $(seq 1 "${attempts}"); do
  if mamba create -y "$@"; then
    exit 0
  fi

  if [ "${attempt}" -ge "${attempts}" ]; then
    echo "mamba create failed after ${attempts} attempt(s): $*" >&2
    exit 1
  fi

  echo "mamba create failed (attempt ${attempt}/${attempts}); cleaning package cache and retrying" >&2
  mamba clean --packages --tarballs -y || true
done
