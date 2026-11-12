#!/usr/bin/env bash
#
# Git LFS for the dev container, from the base image's own distribution.
#
# This replaces ghcr.io/devcontainers/features/git-lfs, which cannot install
# Git LFS on this image without a keyserver. Its apt path is limited to a list
# of releases that stops at bullseye and jammy, so on bookworm it always
# downloads the GitHub release and checks it against signing keys it fetches
# from public keyservers. When none of those hands back a usable key, the
# image fails to build: every branch without a cached layer of its own failed
# "CI-Dev / Run: poetry install" that way in November 2026, with
# "gpg: keyserver receive failed: No data".
#
# Debian's package is verified by the archive keys the image already trusts,
# so nothing here reaches a keyserver. It is an older Git LFS (bookworm has
# 3.3.0), which covers what this repository uses it for: the 'lfs' filter
# that .gitattributes routes images through, pull, and push.
set -euo pipefail

export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get install --no-install-recommends -y git-lfs
rm -rf /var/lib/apt/lists/*

# What 'postCreateCommand' runs, once the workspace is mounted: the
# repository's LFS files, as the replaced feature's 'autoPull' did.
# AUTOPULL is the 'autoPull' option, as features are handed their options.
PULL=/usr/local/share/git-lfs-debian-pull.sh
cat >"${PULL}" <<EOF
#!/bin/sh
set -e
AUTO_PULL=${AUTOPULL:-true}
EOF
cat >>"${PULL}" <<'EOF'
if [ "${AUTO_PULL}" != "true" ]; then
    echo "(!) Skipping 'git lfs pull': 'autoPull' is off"
    exit 0
fi
if ! git lfs ls-files >/dev/null 2>&1; then
    echo "(!) Skipping 'git lfs pull': not in a Git repository"
    exit 0
fi
# The filter for this user, and then the repository's hooks. The workspace
# is usually a checkout made outside the container, whose hooks a newer Git
# LFS may have written, and this older one refuses to replace hooks worded
# differently from its own ("Hook already exists", exit 2).
#
# Whether a hook would still run 'git lfs' is not something to judge by
# reading it: a line can be commented out, or follow an 'exit'. So a refused
# hook is replaced only if it IS a Git LFS hook: a '#!/bin/sh' line, Git
# LFS's guard against 'git-lfs' missing from the PATH (worded differently by
# each version, so only its shape is matched), the one 'git lfs <hook> "$@"'
# line, and nothing else. Then every Git LFS hook is rewritten as this
# version's own. Any other line makes it someone's own hook, and the step
# fails, for them to merge by hand: without a working pre-push hook, a push
# from the container would leave its LFS objects behind.
git lfs install --skip-repo
if ! git lfs update; then
    hooks="$(git rev-parse --git-path hooks)"
    for hook in pre-push post-checkout post-commit post-merge; do
        [ -f "${hooks}/${hook}" ] || continue
        if grep -qvE "^(#!/bin/sh|command -v git-lfs >/dev/null 2>&1 \|\| \{ .*; exit 2; \}|git lfs ${hook} \"\\\$@\"|)$" "${hooks}/${hook}"; then
            echo "(!) ${hooks}/${hook} is not a Git LFS hook: merge it by hand, see 'git lfs update --manual'" >&2
            exit 1
        fi
    done
    echo "(!) Replacing the Git LFS hooks another version wrote with this version's"
    git lfs update --force
fi
git lfs pull
EOF
chmod 755 "${PULL}"
