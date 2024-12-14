#!/usr/bin/env bash

# Shell options for maximum safety:
# -e: Exit on error
# -u: Error on undefined variables
# -o pipefail: Exit on pipe failures
set -euo pipefail

WORKSPACE_DIR="${WORKSPACE_DIR:-/workspaces/partcad}"

conda init

echo "Configuring Git safe directory: ${WORKSPACE_DIR}"
if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
    echo "Failed to configure Git safe directory. Ensure Git is installed and you have proper permissions."
    exit 1
fi

cd "${WORKSPACE_DIR}" || { echo "Failed to change directory to ${WORKSPACE_DIR}. Please verify the directory exists."; exit 1; }
if ! git config --global --add safe.directory "${WORKSPACE_DIR}"; then
    echo "Failed to configure Git safe directory"
    exit 1
fi

install_allure() {
  local allure_url
  allure_url=$(curl -s https://api.github.com/repos/allure-framework/allure2/releases/latest | grep "browser_download_url.*allure_.*_all.deb" | cut -d '"' -f 4)
  if [[ -z "${allure_url}" ]]; then
    echo "Failed to fetch the latest Allure download URL"
    exit 1
  fi
  local allure_deb="/tmp/allure.deb"

  echo "Downloading Allure..."
  if ! curl -JL -o "${allure_deb}" "${allure_url}"; then
    echo "Failed to download Allure"
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
  if ! sudo dpkg -i "${allure_deb}"; then
    echo "Failed to install Allure. Attempting to fix broken dependencies..."
    if ! sudo apt --fix-broken install --yes; then
      echo "Failed to fix broken dependencies"
      exit 1
    fi
  fi

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

install_component "pre-commit hooks" "pre-commit install"
# Verify pre-commit installation
if ! pre-commit --version >/dev/null 2>&1; then
    echo "Pre-commit verification failed"
    exit 1
fi
# Log installed version
echo "Pre-commit version: $(pre-commit --version)"

install_component "poetry export plugin" "poetry self add poetry-plugin-export"
# Verify poetry plugin installation
if ! poetry self show plugins | grep -q "poetry-plugin-export"; then
    echo "Poetry plugin verification failed"
    exit 1
fi
install_component "poetry multiproject plugin" "poetry self add poetry-multiproject-plugin"
# Verify poetry plugin installation
if ! poetry self show plugins | grep -q "poetry-multiproject-plugin"; then
    echo "Poetry plugin verification failed"
    exit 1
fi

# Log installed version
echo "Poetry version: $(poetry --version)"

# Install Git LFS
echo "Installing Git LFS..."
if ! curl -s https://packagecloud.io/install/repositories/github/git-lfs/script.deb.sh | sudo bash; then
  echo "Failed to add Git LFS repository"
  exit 1
fi

if ! sudo apt-get install -y git-lfs; then
  echo "Failed to install Git LFS"
  exit 1
fi

echo "Git LFS installed successfully"


# Install 1Password CLI
echo "Installing 1Password CLI..."

# https://developer.1password.com/docs/cli/get-started/#step-1-install-1password-cli
curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
  sudo gpg --dearmor --output /usr/share/keyrings/1password-archive-keyring.gpg && \
  echo "deb [arch=$(dpkg --print-architecture) signed-by=/usr/share/keyrings/1password-archive-keyring.gpg] https://downloads.1password.com/linux/debian/$(dpkg --print-architecture) stable main" | \
  sudo tee /etc/apt/sources.list.d/1password.list && \
  sudo mkdir -p /etc/debsig/policies/AC2D62742012EA22/ && \
  curl -sS https://downloads.1password.com/linux/debian/debsig/1password.pol | \
  sudo tee /etc/debsig/policies/AC2D62742012EA22/1password.pol && \
  sudo mkdir -p /usr/share/debsig/keyrings/AC2D62742012EA22 && \
  curl -sS https://downloads.1password.com/linux/keys/1password.asc | \
  sudo gpg --dearmor --output /usr/share/debsig/keyrings/AC2D62742012EA22/debsig.gpg && \
  sudo apt update && sudo apt install 1password-cli

# TODO: @alexanderilyin configure 1Password CLI completions
# op completion ...

echo "
╔═════════════════════════════════════════════════════════╗
║ Setup Summary ($(date '+%Y-%m-%d %H:%M:%S'))                    ║
╚═════════════════════════════════════════════════════════╝

- Workspace: ${WORKSPACE_DIR}
- Git LFS: $(git lfs version)
- Allure: $(allure --version)
- Pre-commit: $(pre-commit --version)
- Poetry: $(poetry --version)
- Plugins: $(poetry self show plugins)
- 1Password CLI: $(op --version)

╔═════════════════════════════════════════════════════════╗
║ Dev container post-create setup completed successfully. ║
║ Humor settings: optimal (TARS approved)                 ║
╚═════════════════════════════════════════════════════════╝
"
