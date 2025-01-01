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
