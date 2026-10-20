#!/usr/bin/env bash

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -o pipefail: Exit on pipe failures
set -euo pipefail

# WORKSPACE_DIR="${WORKSPACE_DIR:-/workspaces/partcad}"

# if ! conda init; then
#   echo "Failed to initialize conda"
#   exit 1
# fi

# echo "Configuring Git safe directory: ${WORKSPACE_DIR}"
# if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
#     echo "Failed to configure Git safe directory. Ensure Git is installed and you have proper permissions."
#     exit 1
# fi
#
# cd "${WORKSPACE_DIR}" || { echo "Failed to change directory to ${WORKSPACE_DIR}. Please verify the directory exists."; exit 1; }
# if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
#     echo "Failed to configure Git safe directory"
#     exit 1
# fi

# Allure is pinned, and fetched by name from Maven Central, where Allure
# publishes the same command-line distribution its GitHub releases carry.
#
# It used to be "whatever api.github.com says is latest", asked anonymously.
# The REST API gives an address 60 such requests an hour, and a GitHub-hosted
# runner shares its address with everybody else's jobs. An answer that is not a
# release -- "API rate limit exceeded", a 5xx -- has no .deb in it for `grep` to
# match, and under `pipefail` that failed the assignment and so, under `-e`,
# the whole build, before the check for an empty answer could say a word: exit
# 1 and nothing printed. That is how CI-Dev #2697 died, and why no dev container
# image was ever published for 0.8.224 (only a version bump builds one). A
# file fetched by name is not behind that quota, `--retry` waits out a 429 or a
# 5xx, and a pinned name has a checksum to check.
#
# To move the pin, take the version and the `.tgz.sha256` beside its archive
# from https://repo1.maven.org/maven2/io/qameta/allure/allure-commandline/
ALLURE_VERSION=2.46.1
ALLURE_SHA256=37428164f310c8d137cfdd2c3a25d049b233261ddab13e1bd4dfd7627b5cbf8d

install_allure() {
  local allure_url="https://repo1.maven.org/maven2/io/qameta/allure/allure-commandline/${ALLURE_VERSION}/allure-commandline-${ALLURE_VERSION}.tgz"
  local allure_tgz="/tmp/allure.tgz"

  echo "Downloading Allure ${ALLURE_VERSION}..."
  # -f: an HTTP error is a failure, not an error page saved as the archive.
  if ! curl -fsSL --retry 5 -o "${allure_tgz}" "${allure_url}"; then
    echo "Failed to download Allure from ${allure_url}"
    exit 1
  fi
  if ! echo "${ALLURE_SHA256}  ${allure_tgz}" | sha256sum --check --strict -; then
    echo "Allure ${ALLURE_VERSION} does not match its pinned checksum"
    exit 1
  fi

  echo "Updating package list..."
  if ! sudo apt update; then
    echo "Failed to update package list"
    exit 1
  fi

  echo "Installing required dependencies..."
  if ! sudo apt install --yes default-jre-headless; then
    echo "Failed to install required dependencies"
    exit 1
  fi

  echo "Installing Allure..."
  # The launcher follows its own symlink to find lib/ beside it.
  if ! sudo tar -xzf "${allure_tgz}" -C /opt \
    || ! sudo ln -sf "/opt/allure-${ALLURE_VERSION}/bin/allure" /usr/local/bin/allure; then
    echo "Failed to install Allure"
    exit 1
  fi
  rm -f "${allure_tgz}"

  echo "Allure installed successfully"
}

install_allure

install_component() {
    local component="$1"
    local command="$2"

    # Input validation
    if [[ -z "${component}" || -z "${command}" ]]; then
        echo "Error: Component name and command are required"
        exit 1
    fi

    echo "Installing ${component}..."
    # shellcheck disable=SC2068
    if ! ${command[@]}; then
      echo "Failed to install ${component}"
      exit 1
    fi
}

# install_component "poetry export plugin" "poetry self add poetry-plugin-export"
# # Verify poetry plugin installation
# if ! poetry self show plugins | grep -q "poetry-plugin-export"; then
#     echo "Poetry plugin verification failed"
#     exit 1
# fi
# install_component "poetry multiproject plugin" "poetry self add poetry-multiproject-plugin"
# # Verify poetry plugin installation
# if ! poetry self show plugins | grep -q "poetry-multiproject-plugin"; then
#     echo "Poetry plugin verification failed"
#     exit 1
# fi

# # Log installed version
# echo "Poetry version: $(poetry --version)"

# # Install Git LFS
# echo "Installing Git LFS..."
# if ! curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash; then
#   echo "Failed to add Git LFS repository"
#   exit 1
# fi

echo "
╔═════════════════════════════════════════════════════════╗
║ Setup Summary ($(date '+%Y-%m-%d %H:%M:%S'))                    ║
╚═════════════════════════════════════════════════════════╝

- Allure: $(allure --version)

╔═════════════════════════════════════════════════════════╗
║ Dev container post-create setup completed successfully. ║
║ Humor settings: optimal (TARS approved)                 ║
╚═════════════════════════════════════════════════════════╝
"
