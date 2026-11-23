# PartCAD itself, as an image: `pc`, `pc mcp`, the daemon and the remote Docker
# service, for whoever would rather `docker run` it than install it.
#
#     docker run --rm -it \
#       -v partcad-home:/home/pc/.partcad -v "$PWD:$PWD" -w "$PWD" \
#       ghcr.io/partcad/partcad render my_part
#
# Not a sandbox image, and not one PartCAD ever pulls by itself: those are the
# `partcad-container-*` images beside this directory, which PartCAD resolves and
# replaces on its own. This one is pulled by a person, which is why it is
# published as plain multi-architecture tags (`<version>`, `<major>.<minor>`, `latest`)
# rather than with the `-<arch>` suffix `docker_image.candidates` appends, and
# why `pc system prune` leaves it alone (`partcad.app` below).
#
# Built on the GStreamer flavour of the Python base image, because everything a
# sandbox needs in order to render *inside this container* is already there: the
# shared libraries an OpenCASCADE wheel `dlopen()`s, the prebuilt `pycairo` wheel
# PNG renders need, cadmpeg for the native CAD formats, and GStreamer for the
# video file types. In the base's own terms this is a derived image, and the
# contract in `../README.md` is what it builds on.
#
# Two ways to run it, and both are the same image:
#
# * Without the Docker socket, every CAD script runs in a conda sandbox inside
#   this container -- micromamba, below, which is what provisions an interpreter
#   of whatever version a package asks for. The container is the isolation.
# * With the host's socket mounted, PartCAD finds a daemon and uses its `docker`
#   sandbox, KiCad and plugins' own containers, in `upload` mode
#   (`PC_USE_DOCKER_REMOTE`, below) -- see the README beside this file for why
#   `mount` mode cannot work from in here.
#
# See `README.md` beside this file, and "Docker" in
# `docs/source/installation.rst`, for how it is meant to be run.
#
# Self-contained, so that it builds with nothing but this directory as its
# context: `docker build tools/containers/partcad` installs this release from
# PyPI on this release's base image. That is how Docker's MCP Catalog builds
# `mcp/partcad` out of this repository. `dev-tools/ci/build-partcad-image.sh`
# says more -- the wheel, the base tag, the platforms -- and is how PartCAD's own
# CI and release build it.

# The release this image carries. Moved by bump-my-version with every other
# statement of the release (`dev-tools/bumpversion.toml`), so that a build of
# this file at a release's commit is that release.
ARG PARTCAD_VERSION=0.10.36

# The Python base image this is built on, and its tag without the architecture:
# the release's `<release>-py<version>-gstreamer`, or the tag a CI run built its
# own images under. The architecture is appended from the platform being built,
# because the base images are published per architecture and not as a manifest
# list.
ARG BASE_IMAGE=ghcr.io/partcad/partcad-container-python
ARG BASE_TAG=${PARTCAD_VERSION}-py3.11-gstreamer
ARG TARGETARCH

# Where the wheel comes from: a build context named `wheels` holding exactly one
# partcad wheel, which replaces this empty stage of the same name -- the release
# passes the file it uploaded to PyPI, CI the wheel of the tree under test. With
# nothing passed, this stage is empty and the release is installed from PyPI.
FROM scratch AS wheels

FROM ${BASE_IMAGE}:${BASE_TAG}-${TARGETARCH}

# The reference the image is published as: what `pc init` writes into an
# agent's MCP configuration when it runs in here, and what `pc upgrade` tells
# you to pull instead.
ARG PARTCAD_VERSION
ARG PARTCAD_IMAGE=ghcr.io/partcad/partcad
# The conda this image carries: the same micromamba release the standalone
# bundles carry (`MICROMAMBA_VERSION` in `dev-tools/pyinstaller/build.sh`), and
# a test holds the two to one value.
ARG MICROMAMBA_VERSION=2.9.0-0
ARG TARGETARCH

USER root

# `partcad.image` is inherited from the base and cannot be taken away by a
# derived image, so this says what it is on top: the application a person
# pulled, which `pc system prune` must not delete from under them (see
# `partcad.docker_prune.LABEL_APP`). `io.modelcontextprotocol.server.name` is
# how the MCP Registry decides this image is the server `server.json` names; the
# `org.opencontainers` ones are what GHCR shows on the package's page, and the
# `source` one is what links the package to this repository.
LABEL partcad.app="1" \
      partcad.flavor="app" \
      partcad.version="${PARTCAD_VERSION}" \
      io.modelcontextprotocol.server.name="io.github.partcad/partcad" \
      org.opencontainers.image.title="PartCAD" \
      org.opencontainers.image.description="PartCAD: the pc command line, the MCP server (pc mcp) and the daemon, with conda and OpenSCAD" \
      org.opencontainers.image.source="https://github.com/partcad/partcad" \
      org.opencontainers.image.documentation="https://partcad.readthedocs.io/en/latest/installation.html#docker-image" \
      org.opencontainers.image.licenses="Apache-2.0" \
      org.opencontainers.image.version="${PARTCAD_VERSION}"

# What the base does not carry and a person running PartCAD needs:
#
# * `openscad` -- PartCAD treats it as part of the toolchain (`pc healthcheck`
#   asks after it, and a `.scad` part fails without it); Debian's build, the one
#   `dev-tools/setup-native.sh` installs too, because it exists for both
#   architectures and the bundles' snapshot does not.
# * `git-lfs` -- packages keep their renders and meshes in LFS, and a clone
#   without it holds pointers where the files should be.
# * `tini` -- PID 1. `pc` starts a daemon beside itself, and as PID 1 it would
#   neither reap it nor be stopped by `docker stop`, which sends a SIGTERM that
#   PID 1 ignores unless it installed a handler. The `--init` flag does the same
#   and is one more thing to forget in an MCP client's configuration.
# * `curl` -- what CI scripts run in this image reach for.
#
# Unpinned for the reason the base's own packages are: see DL3008 there.
# hadolint ignore=DL3008
RUN apt-get update \
  && apt-get install --yes --no-install-recommends curl git-lfs openscad tini \
  && rm -rf /var/lib/apt/lists/*

# Every RUN below in bash with pipefail: the checksum is read through a pipe,
# and a download that failed must not reach `sha256sum` as an empty line.
SHELL ["/bin/bash", "-o", "pipefail", "-c"]

# micromamba, installed as itself on PATH, where `partcad_utils.conda` looks for
# it after a `mamba` and a `conda`. Verified against the checksum the release
# publishes beside it, the way the bundles verify theirs.
RUN set -eu; \
    case "${TARGETARCH}" in \
      amd64) artifact=micromamba-linux-64 ;; \
      arm64) artifact=micromamba-linux-aarch64 ;; \
      *) echo "no micromamba build is mapped for ${TARGETARCH}" >&2; exit 1 ;; \
    esac; \
    base="https://github.com/mamba-org/micromamba-releases/releases/download/${MICROMAMBA_VERSION}"; \
    curl -fsSL --retry 5 --retry-all-errors -o /usr/local/bin/micromamba "${base}/${artifact}"; \
    expected="$(curl -fsSL --retry 5 --retry-all-errors "${base}/${artifact}.sha256" | cut -d' ' -f1)"; \
    echo "${expected}  /usr/local/bin/micromamba" | sha256sum --check -; \
    chmod 0755 /usr/local/bin/micromamba; \
    micromamba --version

# PartCAD, with the `lint` extra because the bundles carry it too: the wheel in
# the `wheels` stage above when there is one -- the exact file the release
# uploaded to PyPI, or in a test build the wheel of the tree under test, never a
# second build of the source -- and otherwise this release from PyPI. Either way
# it has to turn out to be `PARTCAD_VERSION`, which is what DL3013 asks for and
# cannot see through the variable.
# hadolint ignore=DL3013
RUN --mount=type=bind,from=wheels,target=/tmp/wheels \
    set -eu; \
    shopt -s nullglob; \
    wheels=(/tmp/wheels/partcad-*-py3-none-any.whl); \
    case "${#wheels[@]}" in \
      0) requirement="partcad[lint]==${PARTCAD_VERSION}" ;; \
      1) requirement="${wheels[0]}[lint]" ;; \
      *) echo "the 'wheels' build context holds ${#wheels[@]} partcad wheels; it may hold one" >&2; exit 1 ;; \
    esac; \
    PIP_ROOT_USER_ACTION=ignore pip install --no-cache-dir "${requirement}"; \
    installed="$(python3 -c 'import partcad_cli; print(partcad_cli.__version__)')"; \
    [ "${installed}" = "${PARTCAD_VERSION}" ] || { echo "installed PartCAD ${installed}, not ${PARTCAD_VERSION}" >&2; exit 1; }

# Where everything PartCAD keeps lives: the base points the state directory at
# `/dot-partcad`, which is right for a sandbox and wrong here, where it is the
# one directory worth keeping in a volume. conda's root prefix -- its package
# cache -- goes in beside the sandboxes, as the bundles put it, so that one
# volume keeps both and `pc system reset` clears both.
#
# Writable by any uid, like the base's `/dot-partcad` and for the same reason:
# the entrypoint runs PartCAD as the owner of the working directory, which is
# 1000 on one machine and 1001 on the next. Sticky, so one uid cannot remove
# another's files. A new named volume is created with this mode.
RUN mkdir -p /home/pc/.partcad /work /workspace /usr/local/share/partcad \
  && chown pc:pc /home/pc/.partcad /work /workspace \
  && chmod 1777 /home/pc /home/pc/.partcad

ENV HOME=/home/pc \
    PC_INTERNAL_STATE_DIR=/home/pc/.partcad \
    MAMBA_ROOT_PREFIX=/home/pc/.partcad/conda \
    PC_USE_DOCKER_REMOTE=true \
    PARTCAD_MANAGED_BY=docker-image \
    PARTCAD_IMAGE=${PARTCAD_IMAGE}

# The names `docker run <image> <name> ...` hands to `pc`, and the options
# before them that take a value, worked out from the wheel just installed
# rather than written down here, so that a new command or option is one
# without anybody remembering this file. See the entrypoint.
RUN python3 -c "import click; from partcad_cli.click.command import cli; \
print('\n'.join(cli.list_commands(click.Context(cli))))" > /usr/local/share/partcad/commands \
  && python3 -c "import click; from partcad_cli.click.command import cli; \
print('\n'.join(o for p in cli.params if isinstance(p, click.Option) and not (p.is_flag or p.count) \
for o in p.opts + p.secondary_opts))" > /usr/local/share/partcad/options \
  && grep -qx render /usr/local/share/partcad/commands \
  && grep -qx mcp /usr/local/share/partcad/commands \
  && grep -qx -- -p /usr/local/share/partcad/options \
  && grep -qx -- --path /usr/local/share/partcad/options \
  && rm -rf /root/.partcad /home/pc/.partcad/* \
  && chmod 1777 /home/pc/.partcad

COPY entrypoint.sh /usr/local/bin/partcad-entrypoint
RUN chmod 0755 /usr/local/bin/partcad-entrypoint

COPY verify.sh /usr/local/share/partcad/verify.sh
RUN sh /usr/local/share/partcad/verify.sh

WORKDIR /work

# Root, so that the entrypoint can become whoever owns the working directory --
# and, given the host's Docker socket, join the group that may use it. It drops
# to that user before PartCAD runs, and `--user` skips it altogether. DL3002
# is about an image whose process stays root, which PartCAD's never does.
# hadolint ignore=DL3002
USER root
ENTRYPOINT ["/usr/bin/tini", "--", "/usr/local/bin/partcad-entrypoint"]
CMD ["--help"]
