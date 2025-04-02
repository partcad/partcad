FROM mcr.microsoft.com/devcontainers/base:bookworm

ARG IMAGE_VERSION=0.7.130

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
# hadolint ignore=DL3007,DL3008,DL3015
COPY --from=ghcr.io/ankitpokhrel/jira-cli:latest /bin/jira /usr/local/bin/jira

SHELL ["/bin/bash", "-c"]

# TODO(clairbee): merge RUN commands even more? any way to reliably cache docker layes in CI?

# Install app APT packages here
# hadolint ignore=DL3004,DL3008
RUN apt-get update -y \
  && apt-get install --no-install-recommends -y \
  # Python 3.10 requirements
  libgdbm-compat-dev \
  # PartCAD VSCode Extension requirements
  nodejs npm \
  # PartCAD VSCode Extension: bundled Python wheels: pillow
  libtiff5-dev libjpeg62-turbo-dev libopenjp2-7-dev zlib1g-dev \
  libfreetype6-dev liblcms2-dev libwebp-dev tcl8.6-dev tk8.6-dev \
  python3-tk libharfbuzz-dev libfribidi-dev libxcb1-dev \
  # PartCAD VSCode Extension: testing
  libatk1.0-0 libatk-bridge2.0-0 libgtk3.0-cil-dev \
  # PartCAD mandatory requirements
  pkg-config \
  libcairo2-dev \
  python3-dev \
  # PartCAD optional requirements
  openscad \
  pypy3 \
  pypy3-dev \
  # Docker troubleshooting tools
  docker.io inetutils-telnet inetutils-ping \
  # Development tools
  file xxd \
  bash-completion \
  cmake \
  graphviz \
  libsm6 \
  libxext6 \
  shellcheck \
  time \
  moreutils \
  # xvfb requirements
  libnss3 \
  libatk1.0-0 \
  libatk-bridge2.0-0 \
  libcups2 \
  libdrm2 \
  libgtk-3-0 \
  libgbm1 \
  libasound2 \
  # xvfb requirements
  xvfb \
  # xvfb related, but possible excessive
  libxext6 \
  libx11-xcb1 \
  libxcb-icccm4 \
  libxcb-image0 \
  libxcb-keysyms1 \
  libxcb-randr0 \
  libxcb-render-util0 \
  libxcb-xinerama0 \
  libxcb-xkb1 \
  && rm -rf /var/lib/apt/lists/*

# TODO(clairbee): install Miniforge securely
# TODO(clairbee): install nvm securely
# TODO: @alexanderilyin: error libmamba Could not open lockfile '/home/vscode/miniforge3/pkgs/cache/cache.lock' \
# TODO: @alexanderilyin: Run `mamba init`

# hadolint ignore=DL3004,DL4006,SC1091
RUN curl -L -O "https://github.com/conda-forge/miniforge/releases/download/24.11.3-0/Miniforge3-$(uname)-$(uname -m).sh" \
  && sudo -u vscode bash "Miniforge3-$(uname)-$(uname -m).sh" -b -p /home/vscode/miniforge3 \
  && sudo -u vscode /home/vscode/miniforge3/condabin/conda init \
  && sudo -u vscode /home/vscode/miniforge3/condabin/conda install -y python=3.10.16 \
  && sudo -u vscode /home/vscode/miniforge3/condabin/conda config --set auto_activate_base true \
  && sudo -u vscode /home/vscode/miniforge3/condabin/conda run python -m pip install poetry pre-commit actionlint-py \
  \
  && (curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.3/install.sh | sudo -u vscode bash) \
  && sudo -u vscode bash -c "(export NVM_DIR=/home/vscode/.nvm && source /home/vscode/.nvm/nvm.sh && nvm install 22 && nvm use 22 && nvm alias default 22)"

# TODO(clairbee): install Node in the following way?
# RUN \
#   curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
#   && apt-get install -y nodejs

ENV DOCKERVERSION=18.03.1-ce
RUN curl -fsSLO https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKERVERSION}.tgz \
  && tar xzvf docker-${DOCKERVERSION}.tgz --strip 1 \
  -C /usr/local/bin docker/docker \
  && rm docker-${DOCKERVERSION}.tgz

# TODO(clairbee): fix the scripts that led to the wrong permissions instead of chmod
# hadolint ignore=DL3004
RUN --mount=type=bind,source=./docker-build-bootstrap.sh,target=/tmp/docker-build-bootstrap.sh \
  --mount=type=bind,source=./docker-build-dbus.sh,target=/tmp/docker-build-dbus.sh \
  /tmp/docker-build-bootstrap.sh \
  && /tmp/docker-build-dbus.sh
