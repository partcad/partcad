#!/usr/bin/env bash
#
# Defines mamba_create_retry: create a conda environment, retrying transient
# package corruption.
#
# conda-forge downloads intermittently land corrupted and mamba aborts the whole
# job with "Found incorrect download: <pkg>" / "<pkg>.tar.bz2 extraction
# failed". The upstream packages are fine on a refetch, so drop the cached
# tarballs and try again rather than losing the run to a bad download.
#
# Source this file rather than executing it: 'mamba' is a shell function set up
# by 'conda init', and a child shell would not inherit it (which on Windows
# leaves no working mamba at all).
#
# Usage: . mamba-create-retry.sh && mamba_create_retry -n <env> [packages...]

mamba_create_retry() {
  local attempts="${MAMBA_CREATE_ATTEMPTS:-3}"
  local attempt

  for attempt in $(seq 1 "${attempts}"); do
    if mamba create -y "$@"; then
      return 0
    fi

    if [ "${attempt}" -ge "${attempts}" ]; then
      echo "mamba create failed after ${attempts} attempt(s): $*" >&2
      return 1
    fi

    echo "mamba create failed (attempt ${attempt}/${attempts}); cleaning package cache and retrying" >&2
    mamba clean --packages --tarballs -y || true
  done
}
