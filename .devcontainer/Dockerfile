FROM mcr.microsoft.com/devcontainers/base:bookworm

ARG IMAGE_VERSION=0.7.96

# https://docs.github.com/en/packages/working-with-a-github-packages-registry/working-with-the-container-registry#labelling-container-images
# https://github.com/opencontainers/image-spec/blob/main/annotations.md
LABEL org.opencontainers.image.source "https://github.com/partcad/partcad.git"
LABEL org.opencontainers.image.description "PartCAD: Development Environment [base:bookworm]"
LABEL org.opencontainers.image.version ${IMAGE_VERSION}
LABEL org.opencontainers.image.licenses "Apache 2.0"
LABEL org.opencontainers.image.documentation "https://partcad.readthedocs.io"

# Set environment variables here (before any RUN commands) to keep them cached.
ENV DISPLAY=127.0.0.1:0
# TODO: Find a way to use ARG $USER_ID
# https://code.visualstudio.com/remote/advancedcontainers/add-nonroot-user#_creating-a-nonroot-user
ENV XDG_RUNTIME_DIR=/run/user/1000
ENV DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus

# COPY file here
COPY --from=ghcr.io/hadolint/hadolint:v2.12.1-beta-debian /bin/hadolint /usr/local/bin/hadolint
# hadolint ignore=DL3007
COPY --from=ghcr.io/ankitpokhrel/jira-cli:latest /bin/jira /usr/local/bin/jira

# TODO(clairbee): merge RUN commands even more? any way to reliably cache docker layes in CI?

# Install app APT packages here
# hadolint ignore=DL3004
RUN sudo apt-get update \
    && sudo apt-get install -y \
      echo "PartCAD VSCode Extension requirements" \
      nodejs npm \
      echo "PartCAD VSCode Extensio: bundled Python wheels: pillow" \
      libtiff5-dev libjpeg62-turbo-dev libopenjp2-7-dev zlib1g-dev \
      libfreetype6-dev liblcms2-dev libwebp-dev tcl8.6-dev tk8.6-dev \
      python3-tk libharfbuzz-dev libfribidi-dev libxcb1-dev \
      echo "PartCAD mandatory requirements" \
      pkg-config \
      libcairo2-dev \
      python3-dev \
      echo "PartCAD optional requirements" \
      openscad \
      pypy3 \
      pypy3-dev \
      echo "Development tools" \
      file xxd \
      bash-completion \
      cmake \
      graphviz \
      libsm6 \
      libxext6 \
      shellcheck \
      time \
    && sudo rm -rf /var/lib/apt/lists/*

# TODO(clairbee): install Miniforge securely
# TODO(clairbee): install nvm securely
# TODO: @alexanderilyin: error libmamba Could not open lockfile '/home/vscode/miniforge3/pkgs/cache/cache.lock' \
# TODO: @alexanderilyin: Run `mamba init`
# hadolint ignore=DL3004,DL4006,SC1091
RUN \
  curl -L -O "https://github.com/conda-forge/miniforge/releases/24.11.3-0/download/Miniforge3-$(uname)-$(uname -m).sh" \
  && sudo -u vscode bash "Miniforge3-$(uname)-$(uname -m).sh" -b -p /home/vscode/miniforge3 \
  \
  && (curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.3/install.sh | bash) \
  && nvm install 22 \
  && nvm use 22 \
  && nvm alias default 22

# TODO(clairbee): install Node in the following way?
# RUN \
#   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - \
#   && sudo apt-get install -y nodejs

# TODO(clairbee): fix the scripts that led to the wrong permissions instead of chmod
# hadolint ignore=DL3004
RUN \
  --mount=type=bind,source=./docker-build-bootstrap.sh,target=/tmp/docker-build-bootstrap.sh \
  --mount=type=bind,source=./docker-build-xvfb.sh,target=/tmp/docker-build-xvfb.sh \
  --mount=type=bind,source=./docker-build-dbus.sh,target=/tmp/docker-build-dbus.sh \
  /tmp/docker-build-bootstrap.sh \
  && /tmp/docker-build-xvfb.sh \
  && /tmp/docker-build-dbus.sh \
  && sudo chown -R "$(whoami):$(whoami)" \
      "/home/$(whoami)/.cache" \
      "/home/$(whoami)/.local/share"
