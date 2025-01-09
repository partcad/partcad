# TODO: @alexanderilyin: Move JIRA CLI installation to Dev Container Templates
# hadolint ignore=DL3007
FROM ghcr.io/ankitpokhrel/jira-cli:latest AS jira

# TODO; @alexanderilyin: Implement SemVer release strategy in https://github.com/partcad/devcontainers-templates/
# hadolint ignore=DL3007
FROM ghcr.io/partcad/devcontainer-partcad:latest

COPY --from=jira /bin/jira /usr/local/bin/jira

# TODO: @alexanderilyin: error libmamba Could not open lockfile '/home/vscode/miniforge3/pkgs/cache/cache.lock' \
# TODO: @alexanderilyin: Run `mamba init`
# hadolint ignore=DL3004
RUN \
  curl -L -O "https://github.com/conda-forge/miniforge/releases/latest/download/Miniforge3-$(uname)-$(uname -m).sh" \
  && sudo -u vscode bash "Miniforge3-$(uname)-$(uname -m).sh" -b -p /home/vscode/miniforge3

# hadolint ignore=DL3004
RUN \
  sudo apt-get update \
  && sudo apt-get install --yes moreutils \
  && sudo rm -rf /var/lib/apt/lists/*

# FROM mcr.microsoft.com/devcontainers/typescript-node:1-22-bookworm
# hadolint ignore=DL4006,SC1091
RUN \
  curl -o- https://raw.githubusercontent.com/nvm-sh/nvm/v0.39.3/install.sh | bash \
  && export NVM_DIR="$HOME/.nvm" \
  && [ -s "$NVM_DIR/nvm.sh" ] && \. "$NVM_DIR/nvm.sh" \
  && nvm install 22 \
  && nvm use 22 \
  && nvm alias default 22

# RUN \
#   curl -fsSL https://deb.nodesource.com/setup_22.x | sudo -E bash - \
#   && sudo apt-get install -y nodejs

RUN \
  --mount=type=bind,source=./xvfb.sh,target=/tmp/xvfb.sh \
  /tmp/xvfb.sh

# RUN set -eux; \
#   apt-get update; \
#   apt-get install --yes --no-install-recommends \
#   gosu=1.14-1+b10; \
#   rm -rf /var/lib/apt/lists/*

ENV DISPLAY=127.0.0.1:0
# TODO: Find a way to use ARG $USER_ID
# https://code.visualstudio.com/remote/advancedcontainers/add-nonroot-user#_creating-a-nonroot-user
ENV XDG_RUNTIME_DIR=/run/user/1000
ENV DBUS_SESSION_BUS_ADDRESS=unix:path=$XDG_RUNTIME_DIR/bus

RUN \
  --mount=type=bind,source=./dbus.sh,target=/tmp/dbus.sh \
  /tmp/dbus.sh
